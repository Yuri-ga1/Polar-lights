"""Docker integration with isolated bind mounts; never use production data.

Run after `docker compose build`. Requires Linux, Docker Compose and free port
18080 (override POLAR_SMOKE_PORT). Temporary fixtures are removed after shutdown.
"""

import fcntl
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
STAMP = "2024-01-01T00:00:00Z"


def eventually(check, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, ValueError, URLError):
            pass
        time.sleep(1)
    raise AssertionError("Timed out waiting for deployment condition")


def main():
    port = os.getenv("POLAR_SMOKE_PORT", "18080")
    base = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="polar-compose-") as directory:
        root = Path(directory)
        shutil.copytree(REPO / "config", root / "config")
        mounts = [f"{root}/config:/app/config:ro"]
        for name in (
            "files/raw",
            "files/processed",
            "files/maps",
            "files/jobs",
            "results",
            "logs",
        ):
            (root / name).mkdir(parents=True)
            mounts.append(f"{root}/{name}:/app/{name}")
        override = root / "override.json"
        override.write_text(
            json.dumps(
                {
                    "services": {
                        name: {
                            "volumes": mounts,
                            "environment": {"POLAR_API_KEY": "smoke-only"},
                        }
                        for name in ("api", "worker")
                    }
                }
            )
        )
        env = {
            **os.environ,
            "POLAR_UID": str(os.getuid()),
            "POLAR_GID": str(os.getgid()),
            "WEB_PORT": port,
        }
        command = [
            "docker",
            "compose",
            "-p",
            f"polar-smoke-{os.getpid()}",
            "-f",
            str(REPO / "compose.yaml"),
            "-f",
            str(override),
        ]

        def compose(*args):
            return subprocess.check_output([*command, *args], env=env, text=True)

        def request(path, body=None, headers=None):
            req = Request(
                base + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers={
                    "X-API-Key": "smoke-only",
                    "Content-Type": "application/json",
                    "X-Request-ID": "smoke-request",
                    **(headers or {}),
                },
            )
            with urlopen(req, timeout=10) as response:
                data = response.read()
                if path.startswith("/api/"):
                    assert response.headers["X-Request-ID"] == "smoke-request"
                return data

        def status(job):
            return json.loads(request(job["statusUrl"]))["status"]

        spec = {
            "productId": "roti-map",
            "parameters": {"timestamp": STAMP, "format": "arrow"},
        }
        try:
            compose(
                "run",
                "--rm",
                "--no-deps",
                "worker",
                "python",
                "-m",
                "deploy.smoke",
                "--fixtures",
                "/app/files",
            )
            compose("up", "-d", "--wait", "--wait-timeout", "180")
            eventually(
                lambda: json.loads(request("/api/v1/ready"))["status"] == "ready"
            )
            assert b"<html" in request("/")
            # A fresh browser session can reload the SPA, with the same server job URL.
            assert b"<html" in request("/workspace/fixture")
            worker_id = compose("ps", "-q", "worker").strip()
            with (root / "files/jobs/heavy.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                job = json.loads(
                    request("/api/v1/data", spec, {"Prefer": "respond-async"})
                )
                eventually(lambda: status(job) == "downloading")
                compose("up", "-d", "--no-deps", "--force-recreate", "api")
                eventually(
                    lambda: json.loads(request("/api/v1/ready"))["status"] == "ready"
                )
                assert compose("ps", "-q", "worker").strip() == worker_id
                assert status(job) == "downloading"
                compose("up", "-d", "--no-deps", "--force-recreate", "frontend")
                eventually(lambda: status(job) == "downloading")
                assert compose("ps", "-q", "worker").strip() == worker_id
                # Host TOML changes reach both processes; the accepted job keeps its snapshot.
                config = root / "config/backend.toml"
                config.write_text(
                    config.read_text().replace("max_days = 31", "max_days = 7")
                )

                def reloaded():
                    state = json.loads(request("/api/v1/config/status"))
                    return (
                        state.get("worker")
                        and state["revision"] == state["worker"]["revision"]
                    )

                time.sleep(2)
                eventually(reloaded)
                with closing(sqlite3.connect(root / "files/jobs/jobs.sqlite3")) as db:
                    snapshot = json.loads(
                        db.execute(
                            "SELECT snapshot FROM job_config WHERE id=?",
                            (job["jobId"],),
                        ).fetchone()[0]
                    )
                    assert snapshot["backend"]["max_days"] == 31
                config.write_text("max_days = [invalid")

                def rejected():
                    state = json.loads(request("/api/v1/config/status"))
                    return state["reloadFailed"] and state["worker"]["reloadFailed"]

                eventually(rejected)
                # Crash an active executor blocked on the heavy lock, then recover persisted work.
                compose("kill", "-s", "SIGKILL", "worker")
                shutil.copyfile(REPO / "config/backend.toml", config)
                compose("up", "-d", "--no-deps", "--force-recreate", "worker")
                fcntl.flock(lock, fcntl.LOCK_UN)
            eventually(lambda: status(job) == "completed", seconds=180)
            result = request(job["resultUrl"])
            assert result
            compose("restart", "api", "frontend")
            eventually(lambda: request(job["resultUrl"]) == result)
            # Cancellation of an active job stays terminal after its child is stopped.
            with (root / "files/jobs/heavy.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                cancelled = json.loads(
                    request("/api/v1/data", spec, {"Prefer": "respond-async"})
                )
                eventually(lambda: status(cancelled) == "downloading")
                req = Request(
                    base + cancelled["statusUrl"],
                    method="DELETE",
                    headers={"X-API-Key": "smoke-only"},
                )
                with urlopen(req, timeout=10) as response:
                    assert response.status < 300
                eventually(lambda: status(cancelled) == "cancelled")
            # A schema-invalid request must preserve API error status through Nginx.
            try:
                request("/api/v1/data", {"productId": "invalid"})
                raise AssertionError("Expected validation error")
            except HTTPError as exc:
                assert exc.code == 422
            with (root / "files/jobs/heavy.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                interrupted = json.loads(
                    request("/api/v1/data", spec, {"Prefer": "respond-async"})
                )
                eventually(lambda: status(interrupted) == "downloading")
                began = time.monotonic()
                compose("stop", "worker")
                assert time.monotonic() - began < 40
                assert status(interrupted) == "retrying"
            compose("down")
            compose("up", "-d", "--wait", "--wait-timeout", "180")
            eventually(lambda: request(job["resultUrl"]) == result)
            eventually(lambda: status(interrupted) == "completed", seconds=180)
            print(
                "PASS: same-origin proxy, API/frontend independence, live config, pinned values, crash recovery, cancellation, persisted results"
            )
        finally:
            print(compose("logs", "--tail", "30"))
            compose("down", "--remove-orphans")


if __name__ == "__main__":
    main()
