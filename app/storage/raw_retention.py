"""Conservative raw lifecycle shared by coordinated acquisition workflows.

Standalone download/load calls retain their original raw-file semantics. Cleanup
only happens inside an operation after its complete result has been read back.
"""

import hashlib
import inspect
import sqlite3
import time
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

import h5py
import pandas as pd
from filelock import FileLock, Timeout

from app.logging_config import get_logger
from app.storage.atomic import publish
from app.storage.timeseries import TimeSeriesStorage, utc

logger = get_logger(__name__)
_operation = ContextVar("raw_operation", default=None)


def raw_lock(folder, timeout=30):
    folder = Path(folder).absolute()
    for parent in (folder, *folder.parents):
        if parent.parent.name == "raw":
            parent.parent.mkdir(parents=True, exist_ok=True)
            return FileLock(
                str(parent.parent / f".{parent.name}.retention.lock"), is_singleton=True
            ).acquire(timeout=timeout)
    return nullcontext()


def raw_locked(action):
    """Protect direct downloader/processor callers as well as queue workers."""

    if inspect.isgeneratorfunction(action):

        @wraps(action)
        def iterate(self, *args, **kwargs):
            with raw_lock(self.folder_path):
                yield from action(self, *args, **kwargs)

        return iterate

    @wraps(action)
    def wrapped(self, *args, **kwargs):
        folder = getattr(self, "folder_path", None) or getattr(self, "out_dir", ".")
        with raw_lock(folder):
            return action(self, *args, **kwargs)

    return wrapped


def processed_operation(action):
    @wraps(action)
    def wrapped(self, *args, **kwargs):
        if self.folder_path is None:
            return action(self, *args, **kwargs)
        with raw_operation(self.folder_path):
            return action(self, *args, **kwargs)

    return wrapped


def preserve_operation():
    operation = _operation.get()
    if operation is not None:
        operation.failed = True


def verify_processed(destination, frame):
    operation = _operation.get()
    if operation is not None:
        operation.verify_frame(destination, frame, durable=False)


def remember_raw(path):
    operation = _operation.get()
    if operation is not None:
        operation.remember(path)
    return path


class RawOperation:
    def __init__(self, folder):
        self.folder = Path(folder).absolute()
        self.enabled = any(
            parent.parent.name == "raw"
            for parent in (self.folder, *self.folder.parents)
        )
        self.files = {}
        self.verified = False
        self.failed = False

    def remember(self, path):
        if not self.enabled:
            return
        path = Path(path).absolute()
        if (
            path.is_relative_to(self.folder)
            and path.is_file()
            and not any(p.is_symlink() for p in (path, *path.parents))
        ):
            self.files[path] = path.stat()

    def verify_frame(self, destination, expected, *, durable=True):
        """Check every incoming column and timestamp, not only the API slice."""
        if not self.enabled:
            return
        expected = TimeSeriesStorage.normalize(expected)
        if expected.empty or not len(expected.columns):
            return
        # Existing notebook CSV writers use replace without fsync. Persist both
        # file contents and the directory entry before any raw input is removed.
        if durable:
            publish(destination, destination)
        saved = TimeSeriesStorage(destination).read()
        actual = saved.loc[expected.index, expected.columns]
        # Existing non-null values may fill missing incoming observations.
        pd.testing.assert_frame_equal(
            actual.where(expected.notna()),
            expected,
            check_freq=False,
            check_dtype=False,
            rtol=1e-12,
            atol=1e-12,
        )
        self.verified = True

    def verify_slices(self, destination, slices):
        import numpy as np

        with h5py.File(destination, "r") as handle:
            by_time = {utc(key): key for key in handle["data"]}
            for timestamp, values in slices.items():
                saved = handle["data"][by_time[utc(timestamp)]][:]
                if saved.dtype != values.dtype:
                    raise ValueError("Published map dtype changed")
                if values.dtype.names:
                    # Structured-array equality treats NaNs as unequal. Compare
                    # each scientific field so valid missing values survive.
                    for field in values.dtype.names:
                        np.testing.assert_array_equal(saved[field], values[field])
                else:
                    np.testing.assert_array_equal(saved, values)
        self.verified = bool(slices)

    def cleanup(self):
        deleted = size = 0
        for path, identity in self.files.items():
            try:
                if path.is_symlink() or not path.exists():
                    continue
                current = path.stat()
                if (
                    current.st_ino,
                    current.st_dev,
                    current.st_size,
                    current.st_mtime_ns,
                ) != (
                    identity.st_ino,
                    identity.st_dev,
                    identity.st_size,
                    identity.st_mtime_ns,
                ):
                    logger.info(
                        "Raw cleanup skipped changed file",
                        extra={
                            "event": "raw_cleanup_skipped",
                            "context": {"reason": "file_changed"},
                        },
                    )
                    continue
                path.unlink()
                deleted += 1
                size += current.st_size if current.st_nlink == 1 else 0
            except OSError:
                logger.warning(
                    "Raw cleanup failed; retained for recovery",
                    extra={"event": "raw_cleanup_failed"},
                    exc_info=True,
                )
        logger.info(
            "Raw cleanup completed",
            extra={
                "event": "raw_cleanup_completed",
                "context": {"files": deleted, "bytes": size},
            },
        )


@contextmanager
def raw_operation(folder, *, timeout=30):
    with raw_lock(folder, timeout=timeout):
        operation = RawOperation(folder)
        token = _operation.set(operation)
        try:
            yield operation
            if operation.verified and not operation.failed:
                operation.cleanup()
        finally:
            _operation.reset(token)


def validate_map(path):
    """Read every point dataset in bounded chunks before raw data can be lost."""
    with h5py.File(path, "r") as handle:
        group = handle["data"]
        if not isinstance(group, h5py.Group) or not len(group):
            raise ValueError("Empty map data")
        times = set()
        for key, dataset in group.items():
            times.add(utc(key))
            names = dataset.dtype.names or ()
            if (
                dataset.ndim != 1
                or not {"lat", "lon"}.issubset(names)
                or not set(names).intersection(("value", "vals", "tec", "roti"))
            ):
                raise ValueError("Invalid map point dataset")
            for first in range(0, len(dataset), 262144):
                dataset[first : first + 262144]
        return times


def _digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()


def _historical_frame(root, source):
    """Parse a complete known source response using its existing processor."""
    kind = source.parent.name
    if kind == "omni":
        from app.omni.omni_processor import OmniProcessor

        processor = OmniProcessor(source.parent)
        pre = processor._extract_pre_block(source.read_text(encoding="utf-8"))
        frame = processor._parse_table(pre, processor._parse_selected_parameters(pre))
    elif kind == "kp":
        from app.gfz.gfz_processor import GfzProcessor

        frame = GfzProcessor.to_processed_frame(GfzProcessor._load_kp_file(source))
    elif kind == "kyoto":
        from app.kyoto.kyoto_dst_processor import KyotoProcessor

        frame = KyotoProcessor(source.parent)._load_month_file(source)
    elif kind == "giro":
        from app.ionosonde.ionosonde_processor import IonosondeProcessor

        frame = IonosondeProcessor(source.parent)._parse_downloaded_text(
            source.read_text(encoding="utf-8")
        )
    elif kind == "nmdb":
        from app.nmdb.nmdb_processor import NmdbProcessor

        processor = NmdbProcessor(source.parent)
        text = processor._keep_only_table(
            processor._strip_html_tags(
                processor._extract_ascii_block(source.read_text(encoding="utf-8"))
            )
        )
        frame = processor._to_amplitude(
            processor._parse_table(text), baseline="median", absolute=False
        )
    else:
        raise ValueError("Unknown raw format")
    # Source-specific notebook CSVs may use raw column names; backend archives
    # use catalog names. Test both without dropping any parsed columns or times.
    from app.backend.catalog import COLUMNS

    mapping = {
        spec.raw_name: spec.name for spec in COLUMNS.values() if spec.source == kind
    }
    destination = root / "processed" / f"{kind}.csv"
    operation = RawOperation(source.parent)
    try:
        operation.verify_frame(destination, frame, durable=False)
    except (KeyError, ValueError, AssertionError):
        operation.verify_frame(
            destination, frame.rename(columns=mapping), durable=False
        )
    if not operation.verified:
        raise ValueError("No complete processed result")
    return destination


def _historical_gim(root, source):
    import io

    from app.simurg.gim_processor import GimProcessor

    with GimProcessor._open_ionex_text(source) as handle:
        text = handle.read()
    if "IONEX VERSION / TYPE" not in text[:200]:
        raise ValueError("Unrecognized GIM response")
    slices = GimProcessor._ionex_maps_to_structured(io.StringIO(text))
    if not slices:
        raise ValueError("No parsed GIM slices")
    entries = {}
    for destination in sorted((root / "maps/gim").glob("*.h5")):
        if any(p.is_symlink() for p in (destination, *destination.parents)):
            raise ValueError("Symlink")
        identity = destination.stat()
        with h5py.File(destination, "r") as handle:
            for key in handle["data"]:
                entries[utc(key)] = (destination, identity)
    grouped = {}
    for timestamp, values in slices.items():
        destination, identity = entries[utc(timestamp)]
        grouped.setdefault((destination, identity), {})[timestamp] = values
    for (destination, _), values in grouped.items():
        RawOperation(source.parent).verify_slices(destination, values)
    return list(grouped)


def cleanup_historical(root, apply=False):
    """Preview/apply only proven duplicates; retain partials and unknown formats."""
    root = Path(root)
    locks = root / "jobs" if (root / "jobs").is_dir() else root
    with FileLock(str(locks / "retention.lock"), timeout=0):
        return _cleanup_historical(root, apply)


def _cleanup_historical(root, apply):
    count = size = skipped = 0
    candidates = sorted(
        p
        for p in (root / "raw").rglob("*")
        if p.is_file() and not p.name.startswith(".")
    )
    for source in candidates:
        proofs = []
        try:
            with raw_lock(source.parent, timeout=0):
                if any(p.is_symlink() for p in (source, *source.parents)):
                    raise ValueError("Symlink")
                if source.parent.parent.name == "simurg" and source.suffix == ".h5":
                    destination = root / "maps" / source.parent.name / source.name
                    if any(p.is_symlink() for p in (destination, *destination.parents)):
                        raise ValueError("Symlink")
                    identity = destination.stat()
                    validate_map(destination)
                    if source.stat().st_size != identity.st_size or _digest(
                        source
                    ) != _digest(destination):
                        raise ValueError("Maps differ")
                elif source.parent == root / "raw/gim" and source.suffix not in (
                    ".part",
                    ".tmp",
                    ".json",
                ):
                    proofs = _historical_gim(root, source)
                    destination, identity = proofs[0]
                elif source.parent.parent == root / "raw" and source.suffix in (
                    ".txt",
                    ".html",
                    ".for",
                ):
                    destination = root / "processed" / f"{source.parent.name}.csv"
                    identity = destination.stat()
                    if any(p.is_symlink() for p in (destination, *destination.parents)):
                        raise ValueError("Symlink")
                    _historical_frame(root, source)
                else:
                    raise ValueError("Unrecognized file or incomplete download")
                # Expensive validation is outside the DB write transaction.
                database = root / "jobs" / "jobs.sqlite3"
                with (
                    sqlite3.connect(database, timeout=2)
                    if database.exists()
                    else nullcontext()
                ) as db:
                    if db:
                        db.execute("BEGIN IMMEDIATE")
                        busy = db.execute(
                            "SELECT 1 FROM jobs WHERE status NOT IN ('completed','failed','cancelled') OR heartbeat > ? LIMIT 1",
                            (time.time() - 60,),
                        ).fetchone()
                        if busy:
                            raise ValueError("Active job may need raw data")
                    if any(
                        path.stat() != stat
                        for path, stat in (proofs or [(destination, identity)])
                    ):
                        raise ValueError("Final result changed during validation")
                    raw_stat = source.stat()
                    size += raw_stat.st_size if raw_stat.st_nlink == 1 else 0
                    count += 1
                    print(f"{'Delete' if apply else 'Would delete'} {source}")
                    if apply:
                        source.unlink()
        except (OSError, ValueError, KeyError, AssertionError, Timeout, sqlite3.Error):
            skipped += 1
            logger.info(
                "Historical raw cleanup skipped file",
                extra={
                    "event": "raw_cleanup_skipped",
                    "context": {"reason": "busy_or_unverified"},
                },
            )
    print(
        f"{'Deleted' if apply else 'Would delete'} {count} raw files; {size} bytes; skipped {skipped}. Unknown formats and partial files retained."
    )
    logger.info(
        "Historical raw cleanup completed",
        extra={
            "event": "raw_cleanup_completed",
            "context": {
                "apply": apply,
                "files": count,
                "bytes": size,
                "skipped": skipped,
            },
        },
    )
    return count, size
