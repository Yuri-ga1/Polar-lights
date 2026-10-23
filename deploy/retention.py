"""Offline terminal-job cleanup. Stop API/worker and back up first."""

import argparse
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

from filelock import FileLock


def cleanup(root, days, apply=False):
    root = Path(root) / "jobs"
    cutoff = time.time() - days * 86400
    with FileLock(str(root / "coordinator.lock"), timeout=0):
        db = sqlite3.connect(root / "jobs.sqlite3", timeout=2)
        try:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT id FROM jobs WHERE status IN ('completed','failed','cancelled') AND updated < ?",
                (cutoff,),
            ).fetchall()
            for (job_id,) in rows:
                if not re.fullmatch(r"[a-f0-9]{32}", job_id):
                    raise ValueError("Unexpected job identifier; refusing cleanup")
                directory = root / job_id
                if directory.is_symlink():
                    raise ValueError("Job directory is a symlink; refusing cleanup")
            print(
                f"{'Deleting' if apply else 'Would delete'} {len(rows)} terminal jobs older than {days} days"
            )
            if apply:
                for (job_id,) in rows:
                    directory = root / job_id
                    if directory.exists():
                        shutil.rmtree(directory)
                    for table in ("job_context", "job_config", "job_secrets", "jobs"):
                        if not db.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (table,),
                        ).fetchone():
                            continue
                        db.execute(f"DELETE FROM {table} WHERE id=?", (job_id,))
                db.commit()
            else:
                db.rollback()
            return len(rows)
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=int(os.getenv("JOB_RETENTION_DAYS", "30"))
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    cleanup(os.getenv("POLAR_DATA_ROOT", "files"), args.days, args.apply)


if __name__ == "__main__":
    main()
