"""Shared, dependency-free structured logging for local application processes."""

from __future__ import annotations

import gzip
import inspect
import json
import logging
import math
import os
import re
import shutil
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import wraps
from itertools import islice
from pathlib import Path

request_id = ContextVar("polar_request_id", default=None)
job_id = ContextVar("polar_job_id", default=None)
run_id = ContextVar("polar_run_id", default=None)
_stage_depth = ContextVar("polar_stage_depth", default=0)
_config_lock = threading.RLock()
_configured = False
_active_config = None
SECRET = re.compile(
    r"password|passwd|secret|token|authorization|cookie|api.?key|email", re.IGNORECASE
)


def redact(value: str) -> str:
    value = re.sub(
        r"https?://[^\s\'\"<>]+",
        lambda m: (
            m[0].split("?")[0].split("#")[0] if "@" not in m[0] else "[redacted URL]"
        ),
        value,
    )
    value = re.sub(r"(?i)(bearer\s+)\S+", r"\1[redacted]", value)
    value = re.sub(
        r"(?i)((?:password|passwd|secret|token|api[_-]?key|authorization|cookie)\s*[=:]\s*)[^\s,;]+",
        r"\1[redacted]",
        value,
    )
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted email]", value)
    # Configured credentials can also appear in an exception without a key label.
    for key, secret in os.environ.items():
        if SECRET.search(key) and len(secret) >= 6:
            value = value.replace(secret, "[redacted]")
    return value[:4096]


def safe(value, depth=0):
    if depth > 4:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (Path, date)):
        return redact(str(value))
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": redact(str(value))}
    if isinstance(value, dict):
        return {
            str(k)[:80]: "[redacted]" if SECRET.search(str(k)) else safe(v, depth + 1)
            for k, v in islice(value.items(), 30)
        }
    if isinstance(value, (tuple, list, set)):
        return [safe(v, depth + 1) for v in islice(value, 20)]
    return {
        "type": type(value).__name__
    }  # Never serialize array/dataframe contents or arbitrary repr.


@dataclass(frozen=True)
class LoggingConfig:
    directory: Path = field(
        default_factory=lambda: Path(os.getenv("POLAR_LOG_DIR", "logs"))
    )
    levels: dict = field(
        default_factory=lambda: {
            s: os.getenv(f"POLAR_LOG_{s.upper()}_LEVEL", "INFO").upper()
            for s in ("frontend", "backend", "pipeline")
        }
    )
    max_bytes: int = field(
        default_factory=lambda: int(os.getenv("POLAR_LOG_MAX_BYTES", "20971520"))
    )
    retention_days: int = field(
        default_factory=lambda: int(os.getenv("POLAR_LOG_RETENTION_DAYS", "30"))
    )
    console: bool = field(
        default_factory=lambda: (
            os.getenv("POLAR_LOG_CONSOLE", "true").lower() in ("true", "1", "yes")
        )
    )
    files: bool = field(
        default_factory=lambda: (
            os.getenv("POLAR_LOG_FILES", "true").lower() in ("true", "1", "yes")
        )
    )


@contextmanager
def file_lock(path, timeout=2):
    """Lock a permanent sidecar, never the inode replaced during rotation."""
    with open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()

            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(handle, fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Logging lock timed out")
                time.sleep(0.01)
        try:
            yield
        finally:
            release()


class JsonFormatter(logging.Formatter):
    def format(self, record):
        service = (
            "backend"
            if record.name.startswith("app.backend")
            else "frontend"
            if record.name.startswith("app.frontend")
            else "pipeline"
        )
        event = getattr(record, "event", "diagnostic_message")
        result = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": service,
            "module": getattr(record, "source_module", record.name),
            "event": event
            if re.fullmatch("[a-z][a-z0-9_]*", event)
            else "diagnostic_message",
            "message": redact(record.getMessage()),
        }
        for key, var in (
            ("request_id", request_id),
            ("job_id", job_id),
            ("run_id", run_id),
        ):
            value = getattr(record, key, None) or var.get()
            if value:
                result[key] = safe(value)
        for key in ("duration_ms", "context", "error"):
            if hasattr(record, key):
                result[key] = safe(getattr(record, key))
        if record.exc_info and record.exc_info[1]:
            exc = record.exc_info[1]
            result["error"] = {
                "type": type(exc).__name__,
                "message": redact(str(exc)),
                "stack": redact("".join(traceback.format_exception(*record.exc_info))),
            }
            if getattr(exc, "code", None) is not None:
                result["error"]["code"] = safe(exc.code)
        return json.dumps(result, ensure_ascii=False, allow_nan=False)


class ComponentHandler(logging.Handler):
    """Open/write/close under one OS lock; workers never retain stale file handles."""

    def __init__(self, service, config):
        super().__init__(config.levels.get(service, "INFO"))
        self.service, self.config = service, config
        self.path = Path(config.directory) / service / f"{service}.jsonl"
        self.setFormatter(JsonFormatter())
        self.last_cleanup = 0

    def emit(self, record):
        try:
            line = self.format(record)
            data = json.loads(line)
            if data["service"] != self.service:
                return
            if self.config.files:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with file_lock(self.path.with_suffix(".lock")):
                    now = time.time()
                    self._rotate(len(line.encode("utf-8")) + 1, now)
                    with self.path.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
                    if now - self.last_cleanup > 3600:
                        for archive in self.path.parent.glob(
                            f"{self.service}.*.jsonl.gz"
                        ):
                            if (
                                archive.stat().st_mtime
                                < now - self.config.retention_days * 86400
                            ):
                                archive.unlink()
                        self.last_cleanup = now
            if self.config.console:
                sys.stderr.write(
                    f"[{data['level']}] {data['module']}: {data['message']}\n"
                )
        except Exception:  # noqa: BLE001, S110 -- Never recurse into a failed logger.
            # Logging is best effort, including formatter, disk, console and lock failures.
            pass

    def _rotate(self, incoming, now):
        if not self.path.exists() or not self.path.stat().st_size:
            return
        stat = self.path.stat()
        old_day = datetime.fromtimestamp(stat.st_mtime, UTC).date()
        if (
            stat.st_size + incoming <= self.config.max_bytes
            and old_day == datetime.fromtimestamp(now, UTC).date()
        ):
            return
        archive = self.path.with_name(
            f"{self.service}.{old_day}.{uuid.uuid4().hex}.jsonl.gz"
        )
        temporary = archive.with_suffix(".tmp")
        try:
            with self.path.open("rb") as source, gzip.open(temporary, "wb") as target:
                shutil.copyfileobj(source, target)
            temporary.replace(archive)
            self.path.unlink()
        finally:
            temporary.unlink(missing_ok=True)


def configure_logging(config=None, *, force=False):
    """Call at entrypoints; repeated notebook cells retain exactly one handler/service."""
    global _configured, _active_config
    with _config_lock:
        if _configured and config is None and not force:
            return
        config = config or LoggingConfig()
        parent = logging.getLogger("app")
        for handler in list(parent.handlers):
            if isinstance(handler, ComponentHandler):
                parent.removeHandler(handler)
                handler.close()
        parent.setLevel(logging.DEBUG)
        parent.propagate = False
        for service in ("frontend", "backend", "pipeline"):
            parent.addHandler(ComponentHandler(service, config))
        _active_config = config
        _configured = True


def get_logging_config():
    """Return the picklable configuration to pass to spawned workers."""
    return _active_config or LoggingConfig()


def get_logger(name):
    return logging.getLogger(name)


@contextmanager
def log_context(**values):
    tokens = [
        (globals()[key], globals()[key].set(value))
        for key, value in values.items()
        if key in ("request_id", "job_id", "run_id")
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def logged_stage(event, *, entry=False):
    """Bounded stage events without changing results or swallowing exceptions."""

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            if entry:
                configure_logging()
            token = (
                run_id.set(uuid.uuid4().hex)
                if entry and not run_id.get() and not job_id.get()
                else None
            )
            depth = _stage_depth.set(_stage_depth.get() + 1)
            logger = get_logger(function.__module__)
            began = time.perf_counter()
            context = {
                "operation": function.__qualname__,
                "source": function.__module__.split(".")[1]
                if "." in function.__module__
                else function.__module__,
            }
            try:
                bound = signature.bind(*args, **kwargs).arguments
                if "self" in bound:
                    source_module = type(bound["self"]).__module__
                    context["source"] = (
                        source_module.split(".")[1]
                        if "." in source_module
                        else source_module
                    )
                config = bound.get("config")
                if config is not None and hasattr(config, "date_str"):
                    context["date_str"] = config.date_str
                for key in (
                    "start",
                    "end",
                    "start_date",
                    "start_datetime",
                    "start_dt",
                    "end_dt",
                    "end_datetime",
                    "date_value",
                    "end_date",
                    "date_str",
                    "target_date",
                    "product",
                    "product_type",
                    "save_path",
                ):
                    if key in bound:
                        context[key] = safe(bound[key])
                logger.info(
                    "Stage started",
                    extra={"event": event + "_started", "context": context},
                )
                result = function(*args, **kwargs)
                if hasattr(result, "shape"):
                    context["shape"] = list(result.shape)
                    if len(result.shape):
                        context["records"] = int(result.shape[0])
                elif isinstance(result, (list, tuple)):
                    context["records"] = len(result)
                logger.info(
                    "Stage completed",
                    extra={
                        "event": event + "_completed",
                        "duration_ms": round((time.perf_counter() - began) * 1000, 3),
                        "context": context,
                    },
                )
                return result
            except Exception:
                # Owning stage logs the stack once; job workers own their failures.
                if (
                    _stage_depth.get() == 1
                    and not job_id.get()
                    and not request_id.get()
                ):
                    logger.exception(
                        "Stage failed",
                        extra={"event": event + "_failed", "context": context},
                    )
                raise
            finally:
                _stage_depth.reset(depth)
                if token is not None:
                    run_id.reset(token)

        return wrapped

    return decorate
