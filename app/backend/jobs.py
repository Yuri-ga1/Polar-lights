"""Durable local queue with bounded, killable workers and restart recovery.

One coordinator is elected with a file lock, even with multiple ASGI workers.
The SQLite database and result artifacts are shared by all HTTP workers.
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

from filelock import FileLock, Timeout
from pydantic import TypeAdapter

from app.logging_config import configure_logging, get_logging_config, logging_from_snapshot
from app.logging_config import request_id as current_request_id
from app.configuration import ConfigurationError, effective_snapshot, manager, pin

from .errors import BackendError
from .logging import get_logger
from .logging import job_id as current_job_id
from .models import DataRequest, MapRenderSpec

logger = get_logger(__name__)
TERMINAL = ("completed", "failed", "cancelled")


class JobStore:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.root / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "jobs.sqlite3"
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, hash TEXT NOT NULL,
                payload TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, error TEXT, media TEXT, files TEXT)""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS job_context (id TEXT PRIMARY KEY, request_id TEXT)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS job_config (id TEXT PRIMARY KEY, snapshot TEXT NOT NULL)")

    def connect(self):
        db = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def submit(self, kind, payload):
        snapshot = effective_snapshot()
        if not hasattr(self.settings, "config_manager"):
            for key in snapshot["backend"]:
                value = getattr(self.settings, key)
                snapshot["backend"][key] = str(value) if isinstance(value, Path) else list(value) if isinstance(value, tuple) else value
        config_json = json.dumps(snapshot, sort_keys=True, allow_nan=False)
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        digest = hashlib.sha256((kind + canonical + config_json).encode()).hexdigest()
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id FROM jobs WHERE hash=? AND status IN ('queued','downloading','processing')",
                (digest,),
            ).fetchone()
            if existing:
                db.commit()
                return existing["id"]
            count = db.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','downloading','processing')"
            ).fetchone()[0]
            if count >= self.settings.max_jobs:
                db.rollback()
                raise BackendError("QUEUE_FULL", "Job queue is full; retry later", 429)
            job_id = uuid.uuid4().hex
            now = time.time()
            db.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
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
                """UPDATE jobs SET status=?,updated=?,error=?,media=COALESCE(?,media),files=COALESCE(?,files)
                          WHERE id=? AND status NOT IN ('completed','failed','cancelled')""",
                (
                    status,
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
        return path, row["media"] or "application/octet-stream"


def execute_job(settings, job_id, logging_config=None):
    """Spawn-safe worker entrypoint. A worker never mutates notebook caches."""
    try:
        config_manager = manager()
        config_manager.start()
    except (ConfigurationError, OSError):
        config_manager = None
    configure_logging(
        logging_from_snapshot(config_manager.snapshot()) if config_manager else logging_config
    )
    job_token = current_job_id.set(job_id)
    began = time.perf_counter()
    store = JobStore(settings)
    row = store.get(job_id)
    with closing(store.connect()) as db:
        context = db.execute(
            "SELECT request_id FROM job_context WHERE id=?", (job_id,)
        ).fetchone()
        config_row = db.execute("SELECT snapshot FROM job_config WHERE id=?", (job_id,)).fetchone()
    snapshot = json.loads(config_row[0]) if config_row else effective_snapshot()
    from .config import Settings

    settings = Settings.from_snapshot(snapshot)
    request_token = current_request_id.set(context[0] if context else None)
    logger.info("Job started", extra={"event": "job_started"})
    try:
        with pin(snapshot):
            _run_job(store, row, settings, job_id)
    except BackendError as exc:
        logger.error("Job failed", exc_info=exc, extra={"event": "job_failure"})
        store.update(job_id, "failed", error=exc.body())
    except Exception:
        logger.exception("jobId=%s worker failed", job_id)
        store.update(
            job_id,
            "failed",
            error=BackendError("PROCESSING_FAILED", "Job processing failed", 500).body(),
        )
    finally:
        logger.info("Job execution finished", extra={"event": "job_finished", "duration_ms": round((time.perf_counter() - began) * 1000, 3)})
        current_request_id.reset(request_token)
        current_job_id.reset(job_token)
        if config_manager:
            config_manager.close()


def _run_job(store, row, settings, job_id):
    snapshot = effective_snapshot()
    from .service import DataService

    service = DataService(settings)
    directory = store.root / job_id
    directory.mkdir(exist_ok=True)
    temporary_config = directory / "effective-config.tmp"
    temporary_config.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    temporary_config.replace(directory / "effective-config.json")
    store.update(job_id, "downloading")
    if row["kind"] == "render":
        from .render import render_maps

        spec = MapRenderSpec.model_validate_json(row["payload"])
        files = render_maps(
            service, spec, directory, lambda: store.update(job_id, "processing")
        )
        store.update(job_id, "completed", files=files, media="image/png")
    else:
        request = TypeAdapter(DataRequest).validate_json(row["payload"])
        payload, media = service.response(request)
        store.update(job_id, "processing")
        temporary = directory / "result.tmp"
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(directory / "result.bin")
        store.update(job_id, "completed", files=["result.bin"], media=media)


class JobRunner:
    def __init__(self, store):
        self.store = store
        self.stop_event = threading.Event()
        self.thread = None
        self.active = {}

    def start(self):
        self.thread = threading.Thread(target=self._run, name="polar-jobs", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

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
            db.execute(
                "UPDATE jobs SET status='failed',error=?,updated=? WHERE status IN ('downloading','processing')",
                (
                    json.dumps(
                        BackendError(
                            "WORKER_RESTARTED", "Worker interrupted; submit again", 503
                        ).body()
                    ),
                    time.time(),
                ),
            )
        context = multiprocessing.get_context("spawn")
        try:
            while not self.stop_event.is_set():
                for job_id, (process, began, limit) in list(self.active.items()):
                    row = self.store.get(job_id)
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
                        if self.store.get(job_id)["status"] not in TERMINAL:
                            self.store.update(
                                job_id,
                                "failed",
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
                            "SELECT id FROM jobs WHERE status='queued' ORDER BY created LIMIT ?",
                            (capacity,),
                        ).fetchall()
                    for row in queued:
                        job_id = row["id"]
                        with closing(self.store.connect()) as db:
                            config_row = db.execute(
                                "SELECT snapshot FROM job_config WHERE id=?", (job_id,)
                            ).fetchone()
                        if config_row:
                            from .config import Settings

                            job_settings = Settings.from_snapshot(json.loads(config_row[0]))
                        else:
                            job_settings = self.store.settings.snapshot() if hasattr(self.store.settings, "snapshot") else self.store.settings
                        limit = job_settings.job_timeout
                        self.store.update(job_id, "downloading")
                        process = context.Process(
                            target=execute_job,
                            args=(job_settings, job_id, get_logging_config()),
                            daemon=True,
                        )
                        process.start()
                        self.active[job_id] = (process, time.monotonic(), limit)
                self.stop_event.wait(0.2)
        finally:
            for job_id, (process, _, _) in self.active.items():
                self._terminate(process)
                self.store.update(
                    job_id,
                    "failed",
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
        if process.is_alive():
            process.kill()
            process.join(timeout=3)
