"""Offline deployment regression coverage; no external scientific services."""

import hashlib
import json
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app.backend.config import Settings
from app.backend.jobs import JobRunner, JobStore, _run_job
from app.configuration import ConfigManager, pin
from deploy.healthcheck import worker_ready
from deploy.retention import cleanup


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(root=self.root)
        self.store = JobStore(self.settings)

    def test_readiness_requires_worker_but_liveness_does_not_start_it(self):
        from app.backend.api import create_app

        app = create_app(self.settings)
        routes = {
            route.path: route.endpoint
            for route in app.routes
            if hasattr(route, "endpoint")
        }
        self.assertEqual(routes["/api/v1/health"]()["status"], "ok")
        self.assertEqual(routes["/api/v1/ready"]().status_code, 503)
        self.assertFalse((self.store.root / "worker-status.json").exists())
        runner = JobRunner(self.store)
        runner.start()
        try:
            for _ in range(100):
                if (self.store.root / "worker-status.json").exists():
                    break
                time.sleep(0.05)
            worker_ready(self.root)
            self.assertEqual(routes["/api/v1/ready"]()["status"], "ready")
        finally:
            runner.close()
        self.assertFalse(runner.thread.is_alive())
        (self.store.root / "worker-status.json").write_text(
            json.dumps({"heartbeatAt": 0})
        )
        self.assertEqual(routes["/api/v1/ready"]().status_code, 503)

    def test_committed_checkpoint_recovers_without_recomputation(self):
        job_id = self.store.submit("data", {"fixture": True})
        directory = self.store.root / job_id
        directory.mkdir()
        result = b"persisted scientific result"
        (directory / "result.bin").write_bytes(result)
        (directory / "artifacts.json").write_text(
            json.dumps(
                {
                    "hashes": {"result.bin": hashlib.sha256(result).hexdigest()},
                    "media": "application/octet-stream",
                }
            )
        )
        with patch(
            "app.backend.service.DataService.response",
            side_effect=AssertionError("must reuse checkpoint"),
        ):
            _run_job(self.store, self.store.get(job_id), self.settings, job_id)
        self.assertEqual(JobStore(self.settings).get(job_id)["status"], "completed")

    def test_cancel_is_terminal_and_cleanup_only_removes_old_terminal_jobs(self):
        cancelled = self.store.submit("data", {"fixture": "cancel"})
        active = self.store.submit("data", {"fixture": "active"})
        self.store.cancel(cancelled)
        self.store.update(cancelled, "completed")
        self.assertEqual(self.store.get(cancelled)["status"], "cancelled")
        with closing(self.store.connect()) as db:
            db.execute("UPDATE jobs SET updated=0")
        self.assertEqual(cleanup(self.root, 30), 1)
        self.assertEqual(self.store.get(cancelled)["status"], "cancelled")
        cleanup(self.root, 30, apply=True)
        self.assertEqual(self.store.get(active)["status"], "queued")

    def test_hot_config_keeps_last_good_and_pinned_snapshot(self):
        config_dir = self.root / "config"
        config_dir.mkdir()
        config_path = config_dir / "backend.toml"
        config_path.write_text("job_workers = 1\nmax_days = 4\n")
        manager = ConfigManager(config_dir, environ={})
        pinned = manager.snapshot()
        config_path.write_text("job_workers = 2\nmax_days = 7\n")
        manager.reload(force=True)
        with pin(pinned):
            self.assertEqual(Settings().max_days, 4)
        self.assertEqual(manager.snapshot()["backend"]["max_days"], 7)
        config_path.write_text("job_workers = [broken")
        manager.reload(force=True)
        self.assertTrue(manager.reload_failed)
        self.assertEqual(manager.snapshot()["backend"]["max_days"], 7)

    def test_renderer_rejects_asset_checksum_mismatch(self):
        from app.backend import setup_render

        response = unittest.mock.Mock(content=b"corrupted asset")
        with (
            patch.object(
                setup_render, "Settings", return_value=Settings(render_assets=self.root)
            ),
            patch.object(setup_render.requests, "get", return_value=response),
            self.assertRaisesRegex(RuntimeError, "checksum mismatch"),
        ):
            setup_render.main()
        self.assertFalse((self.root / "maplibre-gl.js").exists())


if __name__ == "__main__":
    unittest.main()
