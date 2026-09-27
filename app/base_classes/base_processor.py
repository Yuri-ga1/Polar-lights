from __future__ import annotations

from abc import ABC
from datetime import date, datetime, timedelta
import os
from pathlib import Path
from typing import Callable, Iterable, Union

import pandas as pd


class BaseProcessor(ABC):
    """Базовый класс для всех `*Processor` с общими утилитами."""

    def __init__(self, folder_path: str | Path | None = None) -> None:
        self.folder_path: Path | None = Path(folder_path) if folder_path is not None else None

    @staticmethod
    def _parse_date(value: str) -> date:
        return datetime.strptime(value, "%Y-%m-%d").date()

    @staticmethod
    def _coerce_date(value: Union[str, date, datetime]) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return BaseProcessor._parse_date(value)

    def _full_path(self, filename: str) -> str:
        if self.folder_path is None:
            raise ValueError("folder_path не задан")
        return str(self.folder_path / filename)

    @staticmethod
    def _is_non_empty_file(path: str | Path | None) -> bool:
        if path is None:
            return False
        candidate = Path(path)
        return candidate.exists() and candidate.stat().st_size > 0

    time_columns = ("year", "month", "day", "hour", "minute", "second")
    unique_keys: tuple[str, ...] = time_columns
    expected_frequency: timedelta | None = None

    @classmethod
    def _as_utc_naive(cls, value: str | datetime | pd.Timestamp) -> pd.Timestamp:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC").tz_localize(None)
        return timestamp

    @classmethod
    def add_time_columns(cls, frame: pd.DataFrame, column: str = "datetime") -> pd.DataFrame:
        """Return a copy with the canonical UTC time key as its first columns."""
        if frame is None or frame.empty:
            return pd.DataFrame(columns=list(cls.time_columns))
        out = frame.copy()
        if column not in out:
            raise ValueError(f"Missing time column: {column}")
        values = pd.to_datetime(out[column], utc=True, errors="coerce")
        out = out.loc[values.notna()].copy()
        values = values.loc[values.notna()].dt.tz_convert("UTC").dt.tz_localize(None)
        out["year"] = values.dt.year.astype("int64")
        out["month"] = values.dt.month.astype("int64")
        out["day"] = values.dt.day.astype("int64")
        out["hour"] = values.dt.hour.astype("int64")
        out["minute"] = values.dt.minute.astype("int64")
        out["second"] = values.dt.second.astype("int64")
        remaining = [name for name in out.columns if name not in cls.time_columns and name != column]
        return out.loc[:, [*cls.time_columns, *remaining]]

    @classmethod
    def timestamp_series(cls, frame: pd.DataFrame) -> pd.Series:
        if frame is None or frame.empty:
            return pd.Series(dtype="datetime64[ns]")
        return pd.to_datetime(frame.loc[:, list(cls.time_columns)], errors="coerce")

    def read_processed(self, path: str | Path) -> pd.DataFrame:
        candidate = Path(path)
        if not self._is_non_empty_file(candidate):
            return pd.DataFrame(columns=list(self.time_columns))
        frame = pd.read_csv(candidate)
        missing = set(self.time_columns) - set(frame.columns)
        if missing:
            raise ValueError(f"Processed file {candidate} has no time columns: {sorted(missing)}")
        for column in self.time_columns:
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
        return frame

    def update_processed(self, path: str | Path, new_rows: pd.DataFrame, *, unique_keys: Iterable[str] | None = None) -> pd.DataFrame:
        """Merge, de-duplicate, sort and atomically replace a processed CSV."""
        if new_rows is None or new_rows.empty:
            return self.read_processed(path)
        normalized = self.add_time_columns(new_rows)
        old = self.read_processed(path)
        merged = pd.concat([old, normalized], ignore_index=True, sort=False)
        keys = list(unique_keys or self.unique_keys)
        absent = set(keys) - set(merged.columns)
        if absent:
            raise ValueError(f"Unique keys are absent from processed data: {sorted(absent)}")
        merged = merged.drop_duplicates(subset=keys, keep="last")
        order = [*self.time_columns, *[key for key in keys if key not in self.time_columns]]
        merged = merged.sort_values(order, kind="stable")
        for column in self.time_columns:
            merged[column] = merged[column].astype("int64")
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        merged.to_csv(temporary, index=False)
        os.replace(temporary, destination)
        return merged.reset_index(drop=True)

    def select_processed(self, path: str | Path, start: str | datetime, end: str | datetime) -> pd.DataFrame:
        frame = self.read_processed(path)
        if frame.empty:
            return frame
        start_at, end_at = self._as_utc_naive(start), self._as_utc_naive(end)
        if end_at < start_at:
            raise ValueError("end must be greater than or equal to start")
        values = self.timestamp_series(frame)
        return frame.loc[(values >= start_at) & (values <= end_at)].reset_index(drop=True)

    def with_datetime(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Expose the canonical key as a UTC-naive ``datetime`` convenience column."""
        out = frame.copy()
        if not out.empty:
            out.insert(0, "datetime", self.timestamp_series(out))
        return out

    def missing_intervals(self, path: str | Path, start: str | datetime, end: str | datetime) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
        """Find absent expected samples, preserving each source's own cadence."""
        start_at, end_at = self._as_utc_naive(start), self._as_utc_naive(end)
        frame = self.select_processed(path, start_at, end_at)
        present = set(self.timestamp_series(frame).dropna())
        if self.expected_frequency is None:
            expected = pd.date_range(start_at.normalize(), end_at.normalize(), freq="D")
            present = {value.normalize() for value in present}
        else:
            expected = pd.date_range(start_at, end_at, freq=pd.Timedelta(self.expected_frequency))
        missing = [value for value in expected if value not in present]
        if not missing:
            return []
        step = pd.Timedelta(self.expected_frequency or timedelta(days=1))
        intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
        first = previous = missing[0]
        for value in missing[1:]:
            if value != previous + step:
                intervals.append((first, previous))
                first = value
            previous = value
        intervals.append((first, previous))
        return intervals

    def get_data(self, processed_path: str | Path, start: str | datetime, end: str | datetime, acquire_missing: Callable[[list[tuple[pd.Timestamp, pd.Timestamp]]], pd.DataFrame | None], *, unique_keys: Iterable[str] | None = None) -> pd.DataFrame:
        """Processed-first retrieval shared by tabular processors."""
        missing = self.missing_intervals(processed_path, start, end)
        if missing:
            rows = acquire_missing(missing)
            if rows is not None and not rows.empty:
                self.update_processed(processed_path, rows, unique_keys=unique_keys)
        return self.select_processed(processed_path, start, end)
