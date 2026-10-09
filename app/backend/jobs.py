"""Durable local queue with bounded, killable workers and restart recovery.

One coordinator is elected with a file lock, even with multiple ASGI workers.
The SQLite database and result artifacts are shared by all HTTP workers.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import signal
import sqlite3
import threading
import time
import uuid
from contextlib import closing, nullcontext
from contextvars import ContextVar
from pathlib import Path

from filelock import FileLock, Timeout
from pydantic import TypeAdapter

from app.configuration import ConfigurationError, effective_snapshot, manager, pin
from app.logging_config import (
    configure_logging,
    get_logging_config,
    logging_from_snapshot,
)
from app.logging_config import request_id as current_request_id
from app.storage.atomic import publish

from .errors import BackendError
from .logging import get_logger
from .logging import job_id as current_job_id
from .models import DataRequest, MapRenderSpec

logger = get_logger(__name__)
_execution_store = ContextVar("execution_store", default=None)


class ExternalPending(BaseException):
    """Yield execution without being converted into a source failure."""


TERMINAL = ("completed", "failed", "cancelled")


class JobStore:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.root / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "jobs.sqlite3"
        with (
            FileLock(str(self.root / "schema.lock"), timeout=30),
            closing(self.connect()) as db,
        ):
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, hash TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, error TEXT, media TEXT, files TEXT)""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS job_context (id TEXT PRIMARY KEY, request_id TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS job_config (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)"
            )
            # Additive migration serialized against other API/worker startups.
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            for name, definition in {
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "stage": "TEXT",
                "heartbeat": "REAL",
                "started": "REAL",
                "finished": "REAL",
                "next_run": "REAL NOT NULL DEFAULT 0",
                "external": "TEXT",
                "failures": "INTEGER NOT NULL DEFAULT 0",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
            db.execute("PRAGMA user_version=1")
            db.commit()

    def connect(self):
        db = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def submit(self, kind, payload):
        snapshot = effective_snapshot()
        if not hasattr(self.settings, "config_manager"):
            for key in snapshot["backend"]:
                value = getattr(self.settings, key)
                snapshot["backend"][key] = (
                    str(value)
                    if isinstance(value, Path)
                    else list(value)
                    if isinstance(value, tuple)
                    else value
                )
        config_json = json.dumps(snapshot, sort_keys=True, allow_nan=False)
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        digest = hashlib.sha256((kind + canonical + config_json).encode()).hexdigest()
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM jobs WHERE hash=? AND status IN ('queued','downloading','processing','waiting_external','retrying')",
                (digest,),
            ).fetchone()
            if existing:
                db.commit()
                return existing["id"]
            count = db.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','downloading','processing','waiting_external','retrying')"
            ).fetchone()[0]
            if count >= self.settings.max_jobs:
                db.rollback()
                raise BackendError("QUEUE_FULL", "Job queue is full; retry later", 429)
            job_id = uuid.uuid4().hex
            now = time.time()
            db.execute(
                "INSERT INTO jobs (id,kind,hash,payload,status,created,updated,error,media,files) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (job_id, kind, digest, canonical, "queued", now, now, None, None, None),
            )
            db.execute(
                "INSERT OR REPLACE INTO job_context VALUES (?,?)",
                (job_id, current_request_id.get()),
            )
            db.execute("INSERT INTO job_config VALUES (?,?)", (job_id, config_json))
            db.commit()
            logger.info(
                "Job created",
                extra={
                    "event": "job_created",
                    "job_id": job_id,
                    "context": {"kind": kind},
                },
            )
            return job_id

    def get(self, job_id, kind=None):
        with closing(self.connect()) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row or (kind and row["kind"] != kind):
            raise BackendError("JOB_NOT_FOUND", "Unknown job", 404)
        return dict(row)

    def public(self, job_id, kind=None):
        row = self.get(job_id, kind)
        base = "/api/v1/map-render-jobs" if row["kind"] == "render" else "/api/v1/jobs"
        result = {
            "jobId": row["id"],
            "status": row["status"],
            "createdAt": row["created"],
            "updatedAt": row["updated"],
            "stage": row["stage"] or row["status"],
            "attempts": row["attempts"],
            "heartbeatAt": row["heartbeat"],
            "nextRunAt": row["next_run"] or None,
            "startedAt": row["started"],
            "finishedAt": row["finished"],
            "resultUrl": f"{base}/{job_id}/files"
            if row["kind"] == "render"
            else f"{base}/{job_id}/result",
        }
        if row["error"]:
            result["error"] = json.loads(row["error"])
        if row["kind"] == "render":
            from .render import spec_hash

            result["specHash"] = spec_hash(
                MapRenderSpec.model_validate_json(row["payload"])
            )
        return result

    def update(self, job_id, status, *, error=None, media=None, files=None):
        with closing(self.connect()) as db:
            changed = db.execute(
                """UPDATE jobs SET status=?,stage=?,finished=?,updated=?,error=?,media=COALESCE(?,media),files=COALESCE(?,files)
                          WHERE id=? AND status NOT IN ('completed','failed','cancelled')""",
                (
                    status,
                    status,
                    time.time() if status in TERMINAL else None,
                    time.time(),
                    json.dumps(error) if error else None,
                    media,
                    json.dumps(files) if files is not None else None,
                    job_id,
                ),
            )

        if not changed.rowcount:
            return
        logger.info(
            "Job status updated", extra={"event": "job_" + status, "job_id": job_id}
        )

    def defer(self, job_id, *, external=None, error=None):
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row["status"] in TERMINAL:
                db.commit()
                return
            failures = row["failures"] + (1 if error else 0)
            with closing(self.connect()) as config_db:
                saved = config_db.execute(
                    "SELECT snapshot FROM job_config WHERE id=?", (job_id,)
                ).fetchone()
            config = json.loads(saved[0])["backend"] if saved else {}
            exhausted = failures >= config.get("job_max_attempts", 3)
            status = (
                "failed"
                if exhausted
                else "waiting_external"
                if external
                else "retrying"
            )
            delay = min(900, 30 * 2 ** min(failures, 5)) if error else 60
            now = time.time()
            db.execute(
                """UPDATE jobs SET status=?,stage=?,failures=?,next_run=?,updated=?,
                external=COALESCE(?,external),error=?,finished=? WHERE id=?""",
                (
                    status,
                    status,
                    failures,
                    now + delay,
                    now,
                    json.dumps(external) if external else None,
                    json.dumps(error) if error else None,
                    now if exhausted else None,
                    job_id,
                ),
            )
            db.commit()
        logger.info(
            "Job deferred",
            extra={
                "event": "job_" + status,
                "job_id": job_id,
                "context": {"failures": failures, "delay_seconds": delay},
            },
        )

    def retry(self, job_id, kind=None):
        row = self.get(job_id, kind)
        if row["status"] not in ("failed", "cancelled"):
            raise BackendError(
                "JOB_NOT_TERMINAL", "Only failed or cancelled jobs can be retried", 409
            )
        if (
            row["error"]
            and json.loads(row["error"]).get("code") == "REMOTE_SUBMISSION_UNCERTAIN"
        ):
            raise BackendError(
                "REMOTE_SUBMISSION_UNCERTAIN",
                "Resolve ambiguous remote submission with the operator first",
                409,
            )
        return self.submit(row["kind"], json.loads(row["payload"]))

    def cancel(self, job_id, kind=None):
        self.get(job_id, kind)
        self.update(job_id, "cancelled")
        return self.public(job_id, kind)

    def artifact(self, job_id, filename="result.bin", kind=None):
        row = self.get(job_id, kind)
        if row["status"] != "completed":
            raise BackendError(
                "JOB_NOT_COMPLETED", "Result is not ready", 409, jobStatus=row["status"]
            )
        allowed = json.loads(row["files"] or "[]")
        if filename not in allowed or Path(filename).name != filename:
            raise BackendError("FILE_NOT_FOUND", "Unknown artifact", 404)
        path = self.root / row["id"] / filename
        if not path.is_file():
            raise BackendError("STORAGE_ERROR", "Job artifact is missing", 500)
        manifest = path.parent / "artifacts.json"
        if row["attempts"] or manifest.exists():
            try:
                expected = json.loads(manifest.read_text())["hashes"][filename]
                if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError("Artifact checksum mismatch")
            except (OSError, ValueError, KeyError) as exc:
                raise BackendError(
                    "STORAGE_ERROR",
                    "Artifact verification failed; restore from backup or retry",
                    500,
                ) from exc
        return path, row["media"] or "application/octet-stream"


def report_stage(stage):
    """Optional backend hook; notebook calls have no execution store."""
    store = _execution_store.get()
    job_id = current_job_id.get()
    if store and job_id and store.get(job_id)["stage"] != stage:
        store.update(job_id, stage)


def execute_job(settings, job_id, logging_config=None):
    """Spawn-safe worker entrypoint. A worker never mutates notebook caches."""
    # Isolate the process tree so timeout/cancellation also stops Chromium.
    if os.name == "posix":
        os.setsid()

        def stop_tree(*_):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            os.killpg(os.getpid(), signal.SIGTERM)
            raise SystemExit(0)

        signal.signal(signal.SIGTERM, stop_tree)
        if __import__("sys").platform == "linux":
            import ctypes

            parent = os.getppid()
            ctypes.CDLL(None).prctl(1, signal.SIGTERM)
            if os.getppid() != parent or parent == 1:
                stop_tree()
    try:
        config_manager = manager()
        config_manager.start()
    except (ConfigurationError, OSError):
        config_manager = None
    configure_logging(
        logging_from_snapshot(config_manager.snapshot())
        if config_manager
        else logging_config
    )
    job_token = current_job_id.set(job_id)
    began = time.perf_counter()
    store = JobStore(settings)
    row = store.get(job_id)
    store_token = _execution_store.set(store)
    with closing(store.connect()) as db:
        context = db.execute(
            "SELECT request_id FROM job_context WHERE id=?", (job_id,)
        ).fetchone()
        config_row = db.execute(
            "SELECT snapshot FROM job_config WHERE id=?", (job_id,)
        ).fetchone()
    snapshot = json.loads(config_row[0]) if config_row else effective_snapshot()
    from .config import Settings

    settings = Settings.from_snapshot(snapshot)
    request_token = current_request_id.set(context[0] if context else None)
    logger.info("Job started", extra={"event": "job_started"})
    try:
        with pin(snapshot), FileLock(str(store.root / f"{job_id}.lock")):
            if store.get(job_id)["status"] in TERMINAL:
                return
            payload = json.loads(row["payload"])
            heavy = row["kind"] == "render" or payload.get("productId", "").endswith(
                ("map", "keogram")
            )
            with FileLock(str(store.root / "heavy.lock")) if heavy else nullcontext():
                _run_job(store, row, settings, job_id)
    except ExternalPending:
        pass
    except BackendError as exc:
        logger.error(
            "Job failed", extra={"event": "job_failure", "context": {"code": exc.code}}
        )
        if exc.status in (429, 502, 503, 504):
            store.defer(job_id, error=exc.body())
        else:
            store.update(job_id, "failed", error=exc.body())
    except Exception:  # noqa: BLE001 - isolate failures, do not log source secrets
        logger.error("Worker failed", extra={"event": "job_failure"})
        store.defer(
            job_id,
            error=BackendError(
                "PROCESSING_FAILED", "Job processing failed", 500
            ).body(),
        )
    finally:
        logger.info(
            "Job execution finished",
            extra={
                "event": "job_finished",
                "duration_ms": round((time.perf_counter() - began) * 1000, 3),
            },
        )
        current_request_id.reset(request_token)
        current_job_id.reset(job_token)
        _execution_store.reset(store_token)
        if config_manager:
            config_manager.close()


def _run_job(store, row, settings, job_id):
    snapshot = effective_snapshot()
    from .service import DataService

    service = DataService(settings)
    directory = store.root / job_id
    directory.mkdir(exist_ok=True)
    temporary_config = directory / "effective-config.tmp"
    temporary_config.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary_config.replace(directory / "effective-config.json")
    # A committed manifest is the completion checkpoint, not file existence.
    manifest = directory / "artifacts.json"
    if manifest.exists():
        try:
            saved = json.loads(manifest.read_text())
            if all(
                Path(name).name == name
                and hashlib.sha256((directory / name).read_bytes()).hexdigest()
                == digest
                for name, digest in saved["hashes"].items()
            ):
                store.update(
                    job_id,
                    "completed",
                    files=list(saved["hashes"]),
                    media=saved["media"],
                )
                return
        except (OSError, ValueError, KeyError):
            pass
    store.update(job_id, "downloading")
    if row["kind"] == "render":
        from .render import render_maps

        spec = MapRenderSpec.model_validate_json(row["payload"])
        files = render_maps(
            service, spec, directory, lambda: store.update(job_id, "processing")
        )
        media = "image/png"
    else:
        request = TypeAdapter(DataRequest).validate_json(row["payload"])
        payload, media = service.response(request)
        store.update(job_id, "processing")
        temporary = directory / "result.tmp"
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        publish(temporary, directory / "result.bin")
        files = ["result.bin"]
    hashes = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in files
    }
    with (directory / "artifacts.tmp").open("w") as handle:
        json.dump({"hashes": hashes, "media": media}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    publish(directory / "artifacts.tmp", manifest)
    logger.info(
        "Artifacts checkpoint committed",
        extra={"event": "job_checkpoint", "job_id": job_id},
    )
    store.update(job_id, "completed", files=files, media=media)


class JobRunner:
    def __init__(self, store):
        self.store = store
        self.stop_event = threading.Event()
        self.thread = None
        self.active = {}
        self.last_status_write = 0

    def start(self):
        self.thread = threading.Thread(target=self._run, name="polar-jobs", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10 + 6 * max(1, len(self.active)))

    def _run(self):
        lock = FileLock(str(self.store.root / "coordinator.lock"), timeout=0)
        while not self.stop_event.is_set():
            try:
                with lock:
                    self._coordinate()
            except Timeout:
                self.stop_event.wait(1)
            except Exception:
                logger.exception("Job coordinator failed")
                self.stop_event.wait(1)

    def _coordinate(self):
        with closing(self.store.connect()) as db:
            interrupted = db.execute(
                "SELECT id FROM jobs WHERE status IN ('downloading','processing')"
            ).fetchall()
        for row in interrupted:
            self.store.defer(
                row["id"],
                error=BackendError(
                    "WORKER_RESTARTED",
                    "Worker interrupted; retrying from checkpoint",
                    503,
                ).body(),
            )
        context = multiprocessing.get_context("spawn")
        try:
            while not self.stop_event.is_set():
                if time.monotonic() - self.last_status_write >= 5:
                    config = getattr(self.store.settings, "config_manager", None)
                    status = {
                        "heartbeatAt": time.time(),
                        "revision": config.revision if config else None,
                        "reloadFailed": config.reload_failed if config else False,
                        "restartRequired": config.restart_required if config else [],
                    }
                    temporary = self.store.root / "worker-status.tmp"
                    temporary.write_text(json.dumps(status))
                    temporary.replace(self.store.root / "worker-status.json")
                    self.last_status_write = time.monotonic()
                for job_id, (process, began, limit) in list(self.active.items()):
                    row = self.store.get(job_id)
                    with closing(self.store.connect()) as db:
                        db.execute(
                            "UPDATE jobs SET heartbeat=? WHERE id=?",
                            (time.time(), job_id),
                        )
                    timeout = time.monotonic() - began > limit
                    if row["status"] == "cancelled" or timeout:
                        self._terminate(process)
                        if timeout:
                            self.store.update(
                                job_id,
                                "failed",
                                error=BackendError(
                                    "JOB_TIMEOUT", "Job exceeded time limit", 504
                                ).body(),
                            )
                    if not process.is_alive():
                        process.join()
                        if self.store.get(job_id)["status"] in (
                            "downloading",
                            "processing",
                        ):
                            self.store.defer(
                                job_id,
                                error=BackendError(
                                    "PROCESSING_FAILED",
                                    "Worker exited unexpectedly",
                                    500,
                                ).body(),
                            )
                        del self.active[job_id]
                capacity = self.store.settings.job_workers - len(self.active)
                if capacity > 0:
                    with closing(self.store.connect()) as db:
                        queued = db.execute(
                            "SELECT id FROM jobs WHERE status IN ('queued','retrying','waiting_external') AND next_run<=? ORDER BY next_run,created LIMIT ?",
                            (time.time(), self.store.settings.max_jobs),
                        ).fetchall()
                    for row in queued:
                        if self.stop_event.is_set():
                            break
                        if len(self.active) >= self.store.settings.job_workers:
                            break
                        job_id = row["id"]
                        with closing(self.store.connect()) as db:
                            config_row = db.execute(
                                "SELECT snapshot FROM job_config WHERE id=?", (job_id,)
                            ).fetchone()
                        if config_row:
                            from .config import Settings

                            job_settings = Settings.from_snapshot(
                                json.loads(config_row[0])
                            )
                        else:
                            job_settings = (
                                self.store.settings.snapshot()
                                if hasattr(self.store.settings, "snapshot")
                                else self.store.settings
                            )
                        payload = json.loads(self.store.get(job_id)["payload"])
                        heavy = self.store.get(job_id)[
                            "kind"
                        ] == "render" or payload.get("productId", "").endswith(
                            ("map", "keogram")
                        )
                        if heavy and any(
                            self.store.get(active_id)["kind"] == "render"
                            or json.loads(self.store.get(active_id)["payload"])
                            .get("productId", "")
                            .endswith(("map", "keogram"))
                            for active_id in self.active
                        ):
                            continue
                        limit = (
                            job_settings.long_job_timeout
                            if heavy
                            else job_settings.job_timeout
                        )
                        with closing(self.store.connect()) as db:
                            claimed = db.execute(
                                """UPDATE jobs SET status='downloading',stage='downloading',
                                attempts=attempts+1,started=COALESCE(started,?),heartbeat=?,updated=?
                                WHERE id=? AND status IN ('queued','retrying','waiting_external')""",
                                (time.time(), time.time(), time.time(), job_id),
                            )
                        if not claimed.rowcount:
                            continue
                        process = context.Process(
                            target=execute_job,
                            args=(job_settings, job_id, get_logging_config()),
                            daemon=True,
                        )
                        process.start()
                        self.active[job_id] = (process, time.monotonic(), limit)
                self.stop_event.wait(0.2)
        finally:
            for process, _, _ in self.active.values():
                if process.is_alive():
                    process.terminate()
            for job_id, (process, _, _) in self.active.items():
                self._terminate(process)
                if self.store.get(job_id)["status"] not in (
                    "downloading",
                    "processing",
                ):
                    continue
                self.store.defer(
                    job_id,
                    error=BackendError(
                        "WORKER_STOPPED", "Server stopped before completion", 503
                    ).body(),
                )
            self.active.clear()

    @staticmethod
    def _terminate(process):
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.is_alive():
            process.kill()
            process.join(timeout=3)
