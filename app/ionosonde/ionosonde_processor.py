from __future__ import annotations

import glob
import re
from dataclasses import dataclass
from typing import Optional, Union
from datetime import date, datetime

import numpy as np
import pandas as pd

from app.base_classes.base_processor import BaseProcessor


@dataclass(frozen=True)
class IonosondeParseConfig:
    """Parsing settings for autoscaled SCL files."""
    fof2_scale: float = 0.1  # foF2 is stored in 0.1 MHz units
    hf2_scale: float = 1.0   # h'F2 is stored in km units


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
          - we search any station file matching the date first, then any txt.
        """
        if isinstance(date_value, pd.Timestamp):
            d = date_value.date()
        else:
            d = self._parse_date(str(date_value))
        day_anchor = d.strftime("%Y%m%d")

        if station:
            return (
                f"{station}_*_{day_anchor}.txt",
                f"{station}_*.txt",
                "*.txt",
            )

        return (
            f"*_*_{day_anchor}.txt",  # any station, exact date
            f"*_{day_anchor}.txt",    # fallback
            "*.txt",                  # last resort
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

    @staticmethod
    def _digits_to_number(raw: str) -> Optional[int]:
        if raw is None:
            return None
        m = re.search(r"(\d+)", raw)
        return int(m.group(1)) if m else None

    @staticmethod
    def _parse_ts_YYMMDDHHMM(value: str) -> Optional[pd.Timestamp]:
        if not re.fullmatch(r"\d{10}", value):
            return None
        yy = int(value[0:2])
        year = 2000 + yy if yy <= 69 else 1900 + yy
        month = int(value[2:4])
        day = int(value[4:6])
        hour = int(value[6:8])
        minute = int(value[8:10])
        try:
            return pd.Timestamp(year=year, month=month, day=day, hour=hour, minute=minute)
        except Exception:
            return None

    def _parse_downloaded_text(self, raw: str) -> pd.DataFrame:
        records = []
        for ln in raw.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue

            parts = ln.split(maxsplit=1)
            if len(parts) != 2:
                continue

            ts_raw, payload = parts[0], parts[1]
            ts = self._parse_ts_YYMMDDHHMM(ts_raw)
            if ts is None:
                continue

            fields = payload.split("//")
            while fields and fields[-1] == "":
                fields.pop()
            if len(fields) < 5:
                continue

            fof2_raw = fields[-5]
            hf2_raw = fields[-3]

            fof2_int = self._digits_to_number(fof2_raw)
            hf2_int = self._digits_to_number(hf2_raw)

            fof2 = (fof2_int * self.config.fof2_scale) if fof2_int is not None else np.nan
            hmF2 = (hf2_int * self.config.hf2_scale) if hf2_int is not None else np.nan

            if fof2 == 0:
                fof2 = np.nan
            if hmF2 == 0:
                hmF2 = np.nan

            records.append({"datetime": ts, "foF2": fof2, "hmF2": hmF2})

        df = pd.DataFrame.from_records(records)
        if df.empty:
            return df

        df = (
            df.dropna(subset=["datetime"])
            .sort_values("datetime")
            .groupby("datetime", as_index=False)
            .agg({"foF2": "last", "hmF2": "last"})
        )
        return df

    @staticmethod
    def _compute_q_sliding_window(
        df_window: pd.DataFrame,
        target_day: date,
        days_range: int,
        value_col: str,
        q_col: str,
    ) -> pd.DataFrame:
        if df_window is None or df_window.empty:
            return df_window

        tmp = df_window.copy()
        tmp = tmp.sort_values("datetime").reset_index(drop=True)

        tmp["datetime"] = pd.to_datetime(tmp["datetime"], errors="coerce")
        tmp = tmp.dropna(subset=["datetime"])

        mask_target = tmp["datetime"].dt.date == target_day
        out = tmp.loc[mask_target].copy()
        if out.empty:
            return out.drop(columns=[c for c in out.columns if c == q_col], errors="ignore")

        q_values = []
        delta = pd.Timedelta(days=days_range)

        # pre-coerce once for speed
        tmp_vals = pd.to_numeric(tmp[value_col], errors="coerce")

        for t in out["datetime"]:
            left = t - delta
            right = t + delta
            mask = (tmp["datetime"] >= left) & (tmp["datetime"] <= right)
            q_values.append(tmp_vals.loc[mask].mean())

        out[q_col] = pd.Series(q_values, index=out.index).astype("float64").round(1)
        return out

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

        out = self._compute_q_sliding_window(
            df_window, target_day, days_range, "foF2", "foF2q"
        )

        out_hm = self._compute_q_sliding_window(
            df_window, target_day, days_range, "hmF2", "hmF2q"
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

