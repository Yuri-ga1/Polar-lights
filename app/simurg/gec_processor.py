from __future__ import annotations

import pandas as pd

from app.base_classes.base_processor import BaseProcessor
from app.logging_config import logged_stage
from app.storage.raw_retention import raw_locked
from app.storage.timeseries import TimeSeriesStorage


class GecProcessor(BaseProcessor):
    """SIMuRG whitespace CSV: source-dependent UTC grid, -1 is missing GEC.

    Source names remain numeric column names. Normalization is kept in the
    archive name, since the shared time-series store accepts numeric data only.
    """

    @logged_stage("processing")
    @raw_locked
    def load(self, path, sources: list[str]) -> pd.DataFrame:
        frame = pd.read_csv(path, sep=r"\s+")
        calendar = ["Year", "Month", "Day", "DOY", "Hour", "Minute"]
        if list(frame.columns) != [*calendar, "UnixTimestamp", *sources]:
            raise ValueError("Unexpected SIMuRG GEC CSV columns")
        if frame.empty or frame.isna().any().any():
            raise ValueError("Empty or incomplete SIMuRG GEC CSV")
        timestamp = pd.to_datetime(
            pd.to_numeric(frame["UnixTimestamp"], errors="raise"), unit="s", utc=True
        )
        dates = pd.to_datetime(
            frame[[c for c in calendar if c != "DOY"]].rename(columns=str.lower),
            utc=True,
            errors="raise",
        )
        if (
            not timestamp.equals(dates)
            or not (timestamp.dt.dayofyear == frame["DOY"]).all()
        ):
            raise ValueError("Inconsistent SIMuRG GEC timestamps")
        values = frame[sources].apply(pd.to_numeric, errors="raise")
        if (((values < 0) & (values != -1)) | values.eq(float("inf"))).any().any():
            raise ValueError("Invalid GEC value")
        values = values.replace(-1, float("nan"))
        values.insert(0, "datetime", timestamp)
        return TimeSeriesStorage.normalize(values)
