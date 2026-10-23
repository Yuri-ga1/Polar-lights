"""Online terminal-job retention; preview by default, --apply deletes artifacts."""

import argparse
import re
import shutil
import sqlite3
import time
from pathlib import Path

from filelock import FileLock, Timeout

from app.configuration import current
from app.logging_config import configure_logging, get_logger
from app.storage.atomic import publish

logger = get_logger(__name__)


def cleanup(root, days=7, apply=False, *, interval=0):
    if days < 1:
        raise ValueError("Retention must be at least one day")
    root = Path(root) / "jobs"
    if not (root / "jobs.sqlite3").is_file():
        return 0
    now = time.time()
    removed = files = recovered = skipped = 0
    # Independent of the long-lived coordinator lock. Both cleanup callers and
    # executing workers participate in these locks, including cancelled workers.
    with FileLock(str(root / "retention.lock"), timeout=0):
        stamp = root / "retention.timestamp"
        if interval and stamp.exists() and now - float(stamp.read_text()) < interval:
            return 0
        db = sqlite3.connect(root / "jobs.sqlite3", timeout=2)
        try:
            rows = db.execute(
                "SELECT id FROM jobs WHERE status IN ('completed','failed','cancelled') "
                "AND finished < ?",
                (now - days * 86400,),
            ).fetchall()
            for (job_id,) in rows:
                if not re.fullmatch(r"[a-f0-9]{32}", job_id):
                    raise ValueError("Unexpected job identifier; refusing cleanup")
                try:
                    with FileLock(str(root / f"{job_id}.lock"), timeout=0):
                        db.execute("BEGIN IMMEDIATE")
                        eligible = db.execute(
                            "SELECT 1 FROM jobs WHERE id=? AND status IN "
                            "('completed','failed','cancelled') AND finished < ?",
                            (job_id, now - days * 86400),
                        ).fetchone()
                        directory = root / job_id
                        if not eligible or directory.is_symlink():
                            skipped += 1
                            db.rollback()
                            continue
                        artifacts = [
                            p
                            for p in directory.rglob("*")
                            if p.is_file() and not p.is_symlink()
                        ]
                        size = sum(
                            p.stat().st_size
                            for p in artifacts
                            if p.stat().st_nlink == 1
                        )
                        if apply:
                            if directory.exists():
                                shutil.rmtree(directory)
                            for table in (
                                "job_context",
                                "job_config",
                                "job_secrets",
                                "jobs",
                            ):
                                if db.execute(
                                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                                    (table,),
                                ).fetchone():
                                    db.execute(
                                        f"DELETE FROM {table} WHERE id=?", (job_id,)
                                    )
                            # Keep remote intents and uncompleted acquisitions: a
                            # different job may recover their known remote IDs.
                            db.execute(
                                "DELETE FROM simurg_acquisitions WHERE completed=1 AND key NOT IN (SELECT acquisition_key FROM jobs WHERE acquisition_key IS NOT NULL)"
                            )
                            db.commit()
                        else:
                            db.rollback()
                        removed += 1
                        files += len(artifacts)
                        recovered += size
                except Timeout:
                    skipped += 1
                except Exception:
                    db.rollback()
                    raise
            if apply and interval:
                temporary = stamp.with_suffix(".tmp")
                temporary.write_text(str(now))
                publish(temporary, stamp)
        finally:
            db.close()
    logger.info(
        "Job retention completed",
        extra={
            "event": "retention_completed",
            "context": {
                "apply": apply,
                "jobs": removed,
                "files": files,
                "bytes": recovered,
                "skipped_busy_or_changed": skipped,
            },
        },
    )
    print(
        f"{'Deleted' if apply else 'Would delete'} {removed} terminal jobs; {files} files, {recovered} bytes; skipped {skipped}"
    )
    return removed


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=current()["backend"]["job_retention_days"]
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Conservative historical raw cleanup instead of job retention",
    )
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be at least 1")
    root = current()["backend"]["root"]
    if args.raw:
        from app.storage.raw_retention import cleanup_historical

        cleanup_historical(root, apply=args.apply)
    else:
        cleanup(root, args.days, args.apply)


if __name__ == "__main__":
    main()
