"""Small dependency-free container health probes; never start a queue runner."""

import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from urllib.request import Request, urlopen


def worker_ready(root):
    root = Path(root) / "jobs"
    status = json.loads((root / "worker-status.json").read_text())
    if not 0 <= time.time() - status["heartbeatAt"] < 20:
        raise RuntimeError("Worker heartbeat is stale")
    with closing(
        sqlite3.connect(f"file:{root / 'jobs.sqlite3'}?mode=ro", uri=True, timeout=2)
    ) as db:
        db.execute("SELECT id FROM jobs LIMIT 1").fetchone()


def main():
    if sys.argv[1] == "worker":
        worker_ready(os.environ.get("POLAR_DATA_ROOT", "files"))
    else:
        path = "ready" if sys.argv[1] == "ready" else "health"
        request = Request(
            f"http://127.0.0.1:8000/api/v1/{path}",
            headers={"X-API-Key": os.environ.get("POLAR_API_KEY", "")},
        )
        with urlopen(request, timeout=3) as response:
            assert response.status == 200


if __name__ == "__main__":
    main()
