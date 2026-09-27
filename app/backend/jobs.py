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

    def connect(self):
        db = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def submit(self, kind, payload):
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        digest = hashlib.sha256((kind + canonical).encode()).hexdigest()
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
            db.commit()
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
            db.execute(
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


def execute_job(settings, job_id):
    """Spawn-safe worker entrypoint. A worker never mutates notebook caches."""
    current_job_id.set(job_id)
    store = JobStore(settings)
    row = store.get(job_id)
    try:
        from .service import DataService

        service = DataService(settings)
        directory = store.root / job_id
        directory.mkdir(exist_ok=True)
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
    except BackendError as exc:
        store.update(job_id, "failed", error=exc.body())
    except Exception:
        logger.exception("jobId=%s worker failed", job_id)
        store.update(
            job_id,
            "failed",
            error=BackendError(
                "PROCESSING_FAILED", "Job processing failed", 500
            ).body(),
        )


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
                for job_id, (process, began) in list(self.active.items()):
                    row = self.store.get(job_id)
                    timeout = time.monotonic() - began > self.store.settings.job_timeout
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
                        self.store.update(job_id, "downloading")
                        process = context.Process(
                            target=execute_job,
                            args=(self.store.settings, job_id),
                            daemon=True,
                        )
                        process.start()
                        self.active[job_id] = (process, time.monotonic())
                self.stop_event.wait(0.2)
        finally:
            for job_id, (process, _) in self.active.items():
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
