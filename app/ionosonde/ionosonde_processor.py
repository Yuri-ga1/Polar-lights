from __future__ import annotations

import glob
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from typing import Optional, Union

import numpy as np
import pandas as pd

from app.base_classes.base_processor import BaseProcessor


@dataclass(frozen=True)
class IonosondeParseConfig:
    """Parsing settings for autoscaled GIRO text files."""
    fof2_scale: float = 1.0
    hmf2_scale: float = 1.0


class IonosondeProcessor(BaseProcessor):
    def __init__(self, folder_path: str, config: Optional[IonosondeParseConfig] = None) -> None:
        super().__init__(folder_path)
        self.config = config or IonosondeParseConfig()

    # -------------------------
    # file picking
    # -------------------------

    def _build_patterns(
        self,
        date_value: Union[str, pd.Timestamp],
        station: Optional[str] = None,
    ) -> tuple[str, str, str]:
        """
        Downloader creates: {station}_{product}_{dataset}_{YYYYMMDD}.txt

        If station is None:
          - search any station file matching the date first, then any txt.
        """
        if isinstance(date_value, pd.Timestamp):
            d = date_value.date()
        else:
            d = self._parse_date(str(date_value))
        day_anchor = d.strftime("%Y%m%d")

        if station:
            return (
                f"{station}_*_{day_anchor}.txt",
                f"{station}_foF2_hmF2_{day_anchor}.txt",
                f"{station}_*.txt",
                "*.txt",
            )

        return (
            f"*_*_{day_anchor}.txt",
            f"*_foF2_hmF2_{day_anchor}.txt",
            f"*_{day_anchor}.txt",
            "*.txt",
        )

    def _pick_existing_file(self, patterns: tuple[str, str, str]) -> Optional[str]:
        for pat in patterns:
            matches = sorted(glob.glob(self._full_path(pat)))
            for path in matches:
                if self._is_non_empty_file(path):
                    return path
        return None

    # -------------------------
    # parsing helpers
    # -------------------------

    def _parse_downloaded_text(self, raw: str) -> pd.DataFrame:
        """
        Expected data section format:

        #Time                     CS   foF2 QD    hmF2 QD
        2025-10-28T00:00:00.000Z   0 11.800 //  232.5 //
        2025-10-28T00:07:30.000Z  95 11.575 //  232.5 //

        Parsed columns:
          - datetime
          - foF2
          - hmF2
        """
        try:
            df = pd.read_csv(
                StringIO(raw),
                sep=r"\s+",
                comment="#",
                header=None,
                names=["datetime", "CS", "foF2", "QD1", "hmF2", "QD2"],
                engine="python",
            )
        except Exception:
            return pd.DataFrame()

        if df.empty:
            return df

        df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce").dt.tz_localize(None)
        df["foF2"] = pd.to_numeric(df["foF2"], errors="coerce") * self.config.fof2_scale
        df["hmF2"] = pd.to_numeric(df["hmF2"], errors="coerce") * self.config.hmf2_scale

        df["foF2"] = df["foF2"].replace(0, np.nan)
        df["hmF2"] = df["hmF2"].replace(0, np.nan)

        df = (
            df.dropna(subset=["datetime"])
            [["datetime", "foF2", "hmF2"]]
            .sort_values("datetime")
            .groupby("datetime", as_index=False)
            .agg({"foF2": "last", "hmF2": "last"})
        )

        return df

    @staticmethod
    def _compute_q_local_time_mean(
        df_window: pd.DataFrame,
        target_day: date,
        days_range: int,
        value_col: str,
        q_col: str,
    ) -> pd.DataFrame:
        """
        Compute climatological mean using same local time across ±days_range days.
        """

        if df_window is None or df_window.empty:
            return df_window

        tmp = df_window.copy()
        tmp = tmp.sort_values("datetime").reset_index(drop=True)

        tmp["datetime"] = pd.to_datetime(tmp["datetime"], errors="coerce")
        tmp = tmp.dropna(subset=["datetime"])

        tmp[value_col] = pd.to_numeric(tmp[value_col], errors="coerce")

        tmp["tod"] = tmp["datetime"].dt.time

        mask_target = tmp["datetime"].dt.date == target_day
        out = tmp.loc[mask_target].copy()

        if out.empty:
            return out.drop(columns=[c for c in out.columns if c == q_col], errors="ignore")

        q_values = []

        d0 = target_day - pd.Timedelta(days=days_range)
        d1 = target_day + pd.Timedelta(days=days_range)

        for _, row in out.iterrows():
            tod = row["tod"]

            mask = (
                (tmp["datetime"].dt.date >= d0)
                & (tmp["datetime"].dt.date <= d1)
                & (tmp["tod"] == tod)
            )

            q_values.append(tmp.loc[mask, value_col].mean())

        out[q_col] = pd.Series(q_values, index=out.index).astype("float64").round(1)

        return out.drop(columns=["tod"])

    @staticmethod
    def _add_deltas(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out["dfoF2"] = out["foF2"] - out["foF2q"]
        out["dhmF2"] = out["hmF2"] - out["hmF2q"]

        denom = out["foF2q"].replace({0.0: np.nan})
        out["dfoF2p"] = (out["dfoF2"] / denom) * 100.0

        return out

    # -------------------------
    # public
    # -------------------------

    def load(
        self,
        target_date: Union[str, date, datetime],
        station: Optional[str] = None,
        days_range: int = 13,
    ) -> Optional[pd.DataFrame]:
        """
        If station is None, picks the first non-empty file matching the target date.
        """
        target_day = self._coerce_date(target_date)

        patterns = self._build_patterns(date_value=str(target_day), station=station)
        path = self._pick_existing_file(patterns)
        if not self._is_non_empty_file(path):
            return None

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
        except Exception:
            return None

        df = self._parse_downloaded_text(raw)
        if df.empty:
            return None

        dt0 = pd.Timestamp(target_day) - pd.Timedelta(days=days_range)
        dt1 = pd.Timestamp(target_day) + pd.Timedelta(days=days_range + 1)
        df_window = df[(df["datetime"] >= dt0) & (df["datetime"] < dt1)].copy()
        if df_window.empty:
            return None

        out = self._compute_q_local_time_mean(
            df_window,
            target_day,
            days_range,
            "foF2",
            "foF2q",
        )

        out_hm = self._compute_q_local_time_mean(
            df_window,
            target_day,
            days_range,
            "hmF2",
            "hmF2q",
        )

        out["hmF2q"] = out_hm["hmF2q"].values

        out = self._add_deltas(out)

        out = (
            out[
                ["datetime", "foF2", "foF2q", "dfoF2", "dfoF2p", "hmF2", "hmF2q", "dhmF2"]
            ]
            .sort_values("datetime")
            .reset_index(drop=True)
        )

        return out
