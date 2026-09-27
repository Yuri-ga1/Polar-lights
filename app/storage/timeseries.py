"""Shared, process-safe time-series store. No resampling or implicit filling."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from filelock import FileLock

TIME_COLUMNS = ["year", "month", "day", "hour", "minute", "second"]


def utc(value) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("A valid timestamp is required")
    return (
        timestamp.tz_localize("UTC")
        if timestamp.tzinfo is None
        else timestamp.tz_convert("UTC")
    )


def iso(value) -> str:
    return utc(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class FrequencyPolicy:
    seconds: int
    offset_seconds: int = 0

    def expected(self, start, end) -> pd.DatetimeIndex:
        start, end = utc(start), utc(end)
        step = self.seconds * 1_000_000_000
        offset = self.offset_seconds * 1_000_000_000
        first = ((start.value - offset + step - 1) // step) * step + offset
        return pd.date_range(
            pd.Timestamp(first, tz="UTC"), end, freq=pd.Timedelta(seconds=self.seconds)
        )

    def intervals(self, samples) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        samples = sorted(samples)
        if not samples:
            return []
        result = []
        first = previous = samples[0]
        for sample in samples[1:]:
            if sample - previous != pd.Timedelta(seconds=self.seconds):
                result.append((first, previous))
                first = sample
            previous = sample
        return [*result, (first, previous)]


class TimeSeriesStorage:
    """Newest non-null value wins; a null never erases a valid old value."""

    def __init__(self, path: str | Path, lock_timeout: float = 30):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_timeout = lock_timeout

    def lock(self):
        return FileLock(str(self.path) + ".lock", timeout=self.lock_timeout)

    @staticmethod
    def normalize(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        if "datetime" in out:
            index = pd.DatetimeIndex(
                pd.to_datetime(out.pop("datetime"), utc=True, errors="raise")
            )
            out = out.drop(columns=TIME_COLUMNS, errors="ignore")
        elif set(TIME_COLUMNS).issubset(out.columns):
            index = pd.DatetimeIndex(
                pd.to_datetime(out[TIME_COLUMNS], utc=True, errors="raise")
            )
            out = out.drop(columns=TIME_COLUMNS)
        elif isinstance(out.index, pd.DatetimeIndex):
            index = pd.to_datetime(out.index, utc=True)
        elif out.empty:
            return pd.DataFrame(index=pd.DatetimeIndex([], tz="UTC", name="datetime"))
        else:
            raise ValueError("Missing UTC time key")
        if index.hasnans or (index.asi8 % 1_000_000_000).any():
            raise ValueError("Timestamps must be valid and have whole-second precision")
        out.index = index.rename("datetime")
        for column in out:
            out[column] = pd.to_numeric(out[column], errors="raise").astype(float)
        out = out.replace([np.inf, -np.inf], np.nan)
        return out.groupby(level=0).last().sort_index()

    def read(self) -> pd.DataFrame:
        with self.lock():
            return self._read()

    def _read(self):
        if not self.path.exists():
            return self.normalize(pd.DataFrame())
        return self.normalize(pd.read_csv(self.path))

    def merge(self, incoming: pd.DataFrame, *, overwrite: bool = True) -> pd.DataFrame:
        incoming = self.normalize(incoming)
        if incoming.empty:
            return self.read()
        with self.lock():
            old = self._read()
            merged = (
                incoming.combine_first(old)
                if overwrite
                else old.combine_first(incoming)
            )
            merged = merged.reindex(
                columns=list(dict.fromkeys([*old.columns, *incoming.columns]))
            ).sort_index()
            if merged.equals(old):
                return old
            output = merged.reset_index(drop=True)
            for position, column in enumerate(TIME_COLUMNS):
                output.insert(position, column, getattr(merged.index, column))
            fd, name = tempfile.mkstemp(
                prefix=".data-", suffix=".tmp", dir=self.path.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    output.to_csv(handle, index=False)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
            return merged

    @staticmethod
    def version(frame: pd.DataFrame) -> str:
        digest = hashlib.sha256(
            pd.util.hash_pandas_object(frame, index=True).values.tobytes()
        )
        digest.update("|".join(frame.columns).encode())
        return digest.hexdigest()[:24]

    @staticmethod
    def missing(frame, start, end, policies):
        result = {}
        for column, policy in policies.items():
            expected = policy.expected(start, end)
            present = (
                frame.index[frame[column].notna()]
                if column in frame
                else pd.DatetimeIndex([], tz="UTC")
            )
            result[column] = policy.intervals(expected.difference(present))
        return result
