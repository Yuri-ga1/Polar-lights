from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_datetime(value: str | datetime | pd.Timestamp) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().replace(tzinfo=None)

    if isinstance(value, str):
        text = value.strip()
        for fmt in (DATETIME_FORMAT, "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue

    raise ValueError(
        f"Unsupported datetime value: {value!r}. "
        "Use 'YYYY-MM-DD HH:MM:SS'."
    )


def validate_datetime_range(
    start_datetime: str | datetime | pd.Timestamp,
    end_datetime: str | datetime | pd.Timestamp,
) -> tuple[datetime, datetime]:
    start_dt = parse_datetime(start_datetime)
    end_dt = parse_datetime(end_datetime)

    if end_dt < start_dt:
        raise ValueError("end_datetime must be greater than or equal to start_datetime.")

    return start_dt, end_dt


def iter_dates(start_dt: datetime, end_dt: datetime) -> list[str]:
    dates: list[str] = []
    current = start_dt.date()
    end_date = end_dt.date()

    while current <= end_date:
        dates.append(current.isoformat())
        current += timedelta(days=1)

    return dates


def iter_month_anchor_dates(start_dt: datetime, end_dt: datetime) -> list[str]:
    anchors: list[str] = []
    current = start_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_month = end_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    while current <= end_month:
        anchors.append(current.date().isoformat())
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return anchors


def filter_dataframe_by_datetime_range(
    df: pd.DataFrame | None,
    start_dt: datetime,
    end_dt: datetime,
    *,
    time_col: str = "datetime",
) -> pd.DataFrame | None:
    if df is None or df.empty or time_col not in df.columns:
        return df

    out = df.copy()
    out[time_col] = pd.to_datetime(out[time_col], errors="coerce")
    out = out.dropna(subset=[time_col])

    mask = (out[time_col] >= pd.Timestamp(start_dt)) & (out[time_col] <= pd.Timestamp(end_dt))
    return out.loc[mask].sort_values(time_col).reset_index(drop=True)


def concat_dataframes(frames: Iterable[pd.DataFrame | None]) -> pd.DataFrame | None:
    valid = [df for df in frames if df is not None and not df.empty]
    if not valid:
        return None

    out = pd.concat(valid, ignore_index=True)
    if "datetime" in out.columns:
        out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
        out = (
            out.dropna(subset=["datetime"])
            .drop_duplicates(subset=["datetime"], keep="last")
            .sort_values("datetime")
            .reset_index(drop=True)
        )

    return out
