"""Validated, versioned application configuration and one-operation snapshots."""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import logging
import os
import threading
import time
import tomllib
from copy import deepcopy
from pathlib import Path

logger = logging.getLogger(__name__)

# (default, kind, minimum, maximum, application category, legacy environment)
FIELDS = {
    "backend": {
        "root": ("files", str, None, None, "static", "POLAR_DATA_ROOT"),
        "render_assets": ("files/render-assets", str, None, None, "static", "POLAR_RENDER_ASSETS"),
        "cors_origins": ([], list, None, None, "static", "POLAR_CORS_ORIGINS"),
        "max_samples": (200_000, int, 1, 10_000_000, "new", None),
        "max_cells": (1_000_000, int, 1, 100_000_000, "new", None),
        "max_points": (2_000_000, int, 1, 100_000_000, "new", None),
        "max_response_bytes": (64 * 1024 * 1024, int, 1024, 1024**3, "new", None),
        "max_days": (31, int, 1, 3660, "new", None),
        "job_timeout": (1800, int, 1, 86400, "new", None),
        "job_workers": (2, int, 1, 64, "dynamic", None),
        "max_jobs": (32, int, 1, 100_000, "dynamic", None),
    },
    "logging": {
        "directory": ("logs", str, None, None, "static", "POLAR_LOG_DIR"),
        "frontend_level": ("INFO", str, None, None, "dynamic", "POLAR_LOG_FRONTEND_LEVEL"),
        "backend_level": ("INFO", str, None, None, "dynamic", "POLAR_LOG_BACKEND_LEVEL"),
        "pipeline_level": ("INFO", str, None, None, "dynamic", "POLAR_LOG_PIPELINE_LEVEL"),
        "max_bytes": (20_971_520, int, 1024, 1024**3, "dynamic", "POLAR_LOG_MAX_BYTES"),
        "retention_days": (30, int, 1, 3650, "dynamic", "POLAR_LOG_RETENTION_DAYS"),
        "console": (True, bool, None, None, "dynamic", "POLAR_LOG_CONSOLE"),
        "files": (True, bool, None, None, "dynamic", "POLAR_LOG_FILES"),
    },
    "pipeline": {
        "plots_base_dir": ("results", str, None, None, "new", None),
        "observation_source": ("aurorasaurus", str, None, None, "new", None),
    },
    "downloads": {
        "simurg_timeout": (30, int, 1, 600, "new", None),
        "simurg_polling_interval": (60, int, 1, 3600, "new", None),
        "simurg_map_polling_interval": (5, int, 1, 3600, "new", None),
    },
    "plotting": {
        "dpi": (300, int, 30, 1200, "new", None),
    },
}
LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_operation = contextvars.ContextVar("polar_configuration_snapshot", default=None)


class ConfigurationError(ValueError):
    pass


def _validate(section, key, value):
    _, kind, minimum, maximum, _, _ = FIELDS[section][key]
    if type(value) is not kind:
        raise ConfigurationError(f"{section}.{key}: expected {kind.__name__}")
    if kind is str:
        if not value.strip():
            raise ConfigurationError(f"{section}.{key}: must not be empty")
        if key.endswith("level"):
            value = value.upper()
            if value not in LEVELS:
                raise ConfigurationError(f"{section}.{key}: invalid log level")
        if key == "observation_source" and value not in {"aurorasaurus", "spaceweatherlive"}:
            raise ConfigurationError(f"{section}.{key}: unknown source")
    if kind is list:
        if any(type(item) is not str or not item.strip() for item in value):
            raise ConfigurationError(f"{section}.{key}: expected nonempty strings")
        value = list(value)
    if kind is int and not minimum <= value <= maximum:
        raise ConfigurationError(f"{section}.{key}: expected {minimum}..{maximum}")
    return value


def _environment(section, key, raw):
    kind = FIELDS[section][key][1]
    if kind is bool:
        if raw.lower() not in {"true", "false", "1", "0", "yes", "no"}:
            raise ConfigurationError(f"{section}.{key}: invalid environment boolean")
        return raw.lower() in {"true", "1", "yes"}
    if kind is int:
        try:
            return int(raw)
        except ValueError as exc:
            raise ConfigurationError(f"{section}.{key}: invalid environment integer") from exc
    if kind is list:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


def _canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ConfigManager:
    """One watcher per manager. Readers receive copies; publication is atomic."""

    def __init__(self, directory: str | Path = "config", *, interval: float = 0.5, environ=None):
        self.directory = Path(directory)
        self.interval = interval
        self.environ = os.environ if environ is None else environ
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._active = None
        self._revision = None
        self._candidate = None
        self._candidate_at = 0.0
        self.reload(force=True)

    def _read(self):
        result = {}
        signatures = []
        for section, fields in FIELDS.items():
            path = self.directory / f"{section}.toml"
            before = path.stat() if path.exists() else None
            raw = path.read_bytes() if before else b""
            after = path.stat() if path.exists() else None
            if before and not raw:
                raise ConfigurationError(f"{path}: empty file during edit")
            if before and after is None:
                raise ConfigurationError(f"{path}: disappeared during read")
            if before and (before.st_mtime_ns, before.st_size, before.st_ino) != (
                after.st_mtime_ns, after.st_size, after.st_ino
            ):
                raise ConfigurationError(f"{path}: changed during read")
            signatures.append(hashlib.sha256(raw).hexdigest())
            try:
                parsed = tomllib.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeError) as exc:
                raise ConfigurationError(f"{path}: invalid TOML: {exc}") from exc
            if set(parsed) - set(fields):
                raise ConfigurationError(f"{path}: unknown keys: {sorted(set(parsed) - set(fields))}")
            values = {}
            for key, (default, _, _, _, _, env) in fields.items():
                value = parsed.get(key, deepcopy(default))
                if env and env in self.environ:
                    value = _environment(section, key, self.environ[env])
                values[key] = _validate(section, key, value)
            result[section] = values
        return result, tuple(signatures)

    def reload(self, *, force=False):
        """Debounce edits, reject invalid bundles, preserve the last valid snapshot."""
        try:
            candidate, signature = self._read()
            with self._lock:
                if signature == self._revision and not force:
                    return False
                now = time.monotonic()
                if not force and signature != self._candidate:
                    self._candidate, self._candidate_at = signature, now
                    return False
                if not force and now - self._candidate_at < 0.2:
                    return False
                old = self._active
                restart = []
                if old:
                    for section, fields in FIELDS.items():
                        for key, spec in fields.items():
                            if spec[4] == "static" and candidate[section][key] != old[section][key]:
                                restart.append(f"{section}.{key}")
                                candidate[section][key] = deepcopy(old[section][key])
                changed = old is None or candidate != old
                self._active = candidate
                self._revision = signature
                self._candidate = None
            if changed:
                logger.info("Configuration applied", extra={"event": "configuration_applied", "context": {"revision": self.revision}})
                if old and candidate["logging"] != old["logging"]:
                    from app.logging_config import configure_logging, logging_from_snapshot

                    configure_logging(logging_from_snapshot(candidate), force=True)
            if restart:
                logger.warning("Configuration requires restart", extra={"event": "configuration_restart_required", "context": {"keys": restart}})
            return changed
        except (OSError, ConfigurationError) as exc:
            logger.error("Configuration rejected: %s", exc, extra={"event": "configuration_rejected"})
            if force and self._active is None:
                raise
            return False

    @property
    def revision(self):
        with self._lock:
            return hashlib.sha256(_canonical(self._active).encode()).hexdigest()[:16]

    def snapshot(self):
        with self._lock:
            return deepcopy(self._active)

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._watch, name="polar-config", daemon=True)
            self._thread.start()

    def _watch(self):
        while not self._stop.wait(self.interval):
            self.reload()

    def close(self):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None


_default_lock = threading.RLock()
_default_manager = None


def manager():
    global _default_manager
    with _default_lock:
        directory = Path(os.getenv("POLAR_CONFIG_DIR", "config"))
        if _default_manager is None or _default_manager.directory != directory:
            if _default_manager is not None:
                _default_manager.close()
            _default_manager = ConfigManager(directory)
        return _default_manager


def current():
    snapshot = _operation.get()
    if snapshot is not None:
        return snapshot
    instance = manager()
    instance.start()
    return instance.snapshot()


@contextlib.contextmanager
def pin(snapshot=None):
    token = _operation.set(deepcopy(snapshot) if snapshot is not None else current())
    try:
        yield _operation.get()
    finally:
        _operation.reset(token)


def effective_snapshot():
    """Public, secret-free effective settings for job provenance."""
    return current()
