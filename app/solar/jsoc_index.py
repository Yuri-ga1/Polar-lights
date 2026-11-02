"""Shared acquisition state, independent of users and the backend job queue."""

import json
import sqlite3
import time
from contextlib import contextmanager

from app.solar.sdo import SDORecord


class JSOCIndex:
    def __init__(self, paths):
        self.directory = paths.cache / "jsoc"
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.directory / "exports.sqlite"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY, product TEXT NOT NULL, spec TEXT NOT NULL,
                    time_tai TEXT NOT NULL, utc REAL NOT NULL, quality INTEGER NOT NULL,
                    UNIQUE(product, spec, time_tai));
                CREATE INDEX IF NOT EXISTS observation_time ON observations(product, utc);
                CREATE TABLE IF NOT EXISTS local_artifacts (
                    observation TEXT PRIMARY KEY REFERENCES observations(id),
                    raw_path TEXT, map_path TEXT, checksum TEXT, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS exports (
                    id INTEGER PRIMARY KEY, remote_id TEXT, email TEXT,
                    method TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL,
                    checked REAL NOT NULL, urls TEXT, error TEXT, attempts INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS export_items (
                    export INTEGER NOT NULL REFERENCES exports(id),
                    observation TEXT NOT NULL REFERENCES observations(id),
                    PRIMARY KEY(export, observation));
                CREATE TABLE IF NOT EXISTS lookup_cache (
                    product TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
                    expires REAL NOT NULL, PRIMARY KEY(product, start, end));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def remember(self, product, records, start, end, ttl):
        with self.connect() as db:
            for record in records:
                db.execute(
                    "INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?)",
                    (
                        record.identity(product),
                        product.key,
                        record.spec,
                        record.time_tai,
                        record.utc.timestamp(),
                        record.quality,
                    ),
                )
            db.execute(
                "INSERT OR REPLACE INTO lookup_cache VALUES (?,?,?,?)",
                (product.key, start, end, time.time() + ttl),
            )

    def candidates(self, product, start, end):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM observations WHERE product=? AND utc BETWEEN ? AND ?",
                (product.key, start, end),
            ).fetchall()
        return [
            SDORecord(row["spec"], row["time_tai"], row["quality"])
            for row in rows
            if not row["quality"] & product.quality_mask
        ]

    def covered(self, product, start, end):
        with self.connect() as db:
            return bool(
                db.execute(
                    "SELECT 1 FROM lookup_cache WHERE product=? AND start<=? AND end>=? AND expires>?",
                    (product.key, start, end, time.time()),
                ).fetchone()
            )

    def artifact(self, identity):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM local_artifacts WHERE observation=?", (identity,)
            ).fetchone()
            return dict(row) if row else {}

    def artifact_update(self, identity, **fields):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO local_artifacts(observation,status) VALUES (?,'known')",
                (identity,),
            )
            for field, value in fields.items():
                if field not in ("raw_path", "map_path", "checksum", "status"):
                    raise ValueError(field)
                db.execute(
                    f"UPDATE local_artifacts SET {field}=? WHERE observation=?",
                    (value, identity),
                )

    def latest_export(self, identity, method):
        with self.connect() as db:
            row = db.execute(
                "SELECT e.* FROM exports e JOIN export_items i ON i.export=e.id WHERE i.observation=? AND e.method=? AND e.status NOT IN ('unusable','invalid') ORDER BY e.id DESC LIMIT 1",
                (identity, method),
            ).fetchone()
            return dict(row) if row else None

    def reserve_export(self, identity, method, email):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO exports(method,email,status,created,checked) VALUES (?,?,'submitting',?,?)",
                (method, email, time.time(), time.time()),
            )
            key = cursor.lastrowid
            db.execute("INSERT INTO export_items VALUES (?,?)", (key, identity))
            return key

    def export_update(self, key, **fields):
        with self.connect() as db:
            for field, value in fields.items():
                if field not in (
                    "remote_id",
                    "status",
                    "checked",
                    "urls",
                    "error",
                    "attempts",
                ):
                    raise ValueError(field)
                if field == "urls":
                    value = json.dumps(value)
                db.execute(f"UPDATE exports SET {field}=? WHERE id=?", (value, key))
