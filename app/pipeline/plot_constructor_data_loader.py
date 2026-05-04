from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timedelta

import pandas as pd

from app.pipeline.observation_pipeline import (
    collect_observation_links,
    load_observations_from_csv,
    parse_and_save_observations,
)
from app.storage.hdf5_storage import ObservationHDF5Storage

from app.gfz.gfz_downloader import GfzDownloader
from app.gfz.gfz_processor import GfzProcessor
from app.kyoto.kyoto_dst_downloader import KyotoDstDownloader
from app.kyoto.kyoto_dst_processor import KyotoProcessor
from app.simurg.gim_downloader import GimDownloader
from app.simurg.gim_processor import GimProcessor
from app.simurg.simurg_client import SimurgClient
from app.simurg.simurg_downloader import RotiDownloader, AdjustedTecDownloader
from app.simurg.simurg_processor import SimurgProcessor, DataProduct
from app.ionosonde.ionosonde_downloader import IonosondeDownloader
from app.ionosonde.ionosonde_processor import IonosondeProcessor
from app.nmdb.nmdb_downloader import NmdbDownloader
from app.nmdb.nmdb_processor import NmdbProcessor


@dataclass
class ConstructorDataConfig:
    date_start: str
    date_end: str
    base_dir: str = "files"
    simurg_email: str | None = None


class PlotConstructorDataLoader:
    def __init__(self, config: ConstructorDataConfig) -> None:
        self.config = config

        self.start_dt = self._parse_datetime(config.date_start)
        self.end_dt = self._parse_datetime(config.date_end)

        if self.end_dt < self.start_dt:
            raise ValueError("date_end must be greater than or equal to date_start")

        self.primary_date_str = self.start_dt.strftime("%Y-%m-%d")
        self.download_dates = self._resolve_daily_dates(self.start_dt, self.end_dt)

        parents_dir = Path.cwd().parent
        download_dir = parents_dir / config.base_dir
        self.date_dir = os.path.join(download_dir, self.primary_date_str)

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        value = value.strip()

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

        raise ValueError(
            f"Unsupported datetime format: {value}. "
            "Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"
        )

    @staticmethod
    def _resolve_daily_dates(start_dt: datetime, end_dt: datetime) -> list[str]:
        dates: list[str] = []
        current = start_dt.date()
        end_date = end_dt.date()

        while current <= end_date:
            if (
                current == end_date
                and end_dt.time() == datetime.min.time()
                and end_dt > start_dt
            ):
                break

            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        return dates or [start_dt.strftime("%Y-%m-%d")]

    @staticmethod
    def _normalize(name: str) -> str:
        return " ".join(name.lower().replace("_", " ").split())

    def _contains(self, requested: set[str], *names: str) -> bool:
        return any(self._normalize(name) in requested for name in names)

    @classmethod
    def _merge_plot_params(cls, plots: list[str | dict[str, Any]]) -> dict[str, dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        for item in plots:
            if isinstance(item, str):
                continue

            name = cls._normalize(str(item.get("name", "")))
            if not name:
                continue

            merged.setdefault(name, {}).update(dict(item.get("params", {})))

        return merged

    @staticmethod
    def _safe_download(fn):
        try:
            return fn()
        except Exception as exc:
            print(f"Download warning: {exc}")
            return None

    def _simurg_client(self, email: str | None = None) -> SimurgClient | None:
        resolved_email = email or self.config.simurg_email
        if not resolved_email:
            return None

        return SimurgClient(email=resolved_email)

    def _load_kp(self):
        out_dir = os.path.join(self.date_dir, "kp")
        os.makedirs(out_dir, exist_ok=True)

        for date_str in self.download_dates:
            self._safe_download(
                lambda d=date_str: GfzDownloader(out_dir=out_dir).download(
                    date_str=d,
                    fmt="kp2",
                )
            )

        return GfzProcessor(folder_path=out_dir).load(date_str=self.primary_date_str)

    def _load_dst(self):
        out_dir = os.path.join(self.date_dir, "kyoto")
        os.makedirs(out_dir, exist_ok=True)

        for date_str in self.download_dates:
            self._safe_download(
                lambda d=date_str: KyotoDstDownloader(out_dir=out_dir).download(d)
            )

        return KyotoProcessor(folder_path=out_dir).load(self.primary_date_str)

    def _load_roti(self, params: dict[str, Any] | None = None):
        params = params or {}

        client = self._simurg_client(params.get("email"))
        if client is None:
            print("SIMURG email is missing, skip ROTI download")
            return None

        out_dir = os.path.join(self.date_dir, "simurg")
        os.makedirs(out_dir, exist_ok=True)

        self._safe_download(
            lambda: RotiDownloader(client=client, out_dir=out_dir).download(
                self.primary_date_str
            )
        )

        target_date = datetime.strptime(self.primary_date_str, "%Y-%m-%d").date() - timedelta(days=1)

        return SimurgProcessor(folder_path=out_dir).load(
            target_date,
            product_type=DataProduct.ROTI,
            times=params.get("time"),
        )

    def _load_adjusted_tec(self, params: dict[str, Any] | None = None):
        params = params or {}

        client = self._simurg_client(params.get("email"))
        if client is None:
            print("SIMURG email is missing, skip adjusted TEC download")
            return None

        out_dir = os.path.join(self.date_dir, "simurg")
        os.makedirs(out_dir, exist_ok=True)

        self._safe_download(
            lambda: AdjustedTecDownloader(client=client, out_dir=out_dir).download(
                self.primary_date_str
            )
        )

        return SimurgProcessor(folder_path=out_dir).load(
            self.primary_date_str,
            product_type=DataProduct.TEC_ADJUSTED,
            times=params.get("time"),
        )

    def _load_gim(self, params: dict[str, Any] | None = None):
        params = params or {}
        product_type = str(params.get("product_type", "uqrg")).lower()

        out_dir = os.path.join(self.date_dir, "gim")
        os.makedirs(out_dir, exist_ok=True)

        for date_str in self.download_dates:
            self._safe_download(
                lambda d=date_str: GimDownloader(
                    out_dir=out_dir,
                    gim_type=product_type,
                ).download(d)
            )

        return GimProcessor(folder_path=out_dir).load(self.primary_date_str)

    def _load_ionosonde(self, params: dict[str, Any] | None = None):
        params = params or {}
        code = params.get("code")
        station = None if code is None else (code[0] if isinstance(code, list) else code)

        out_dir = os.path.join(self.date_dir, "ionosonde")
        os.makedirs(out_dir, exist_ok=True)

        IonosondeDownloader(out_dir=out_dir).download(
            target_date=self.primary_date_str,
            station=station,
        )

        return IonosondeProcessor(folder_path=out_dir).load(
            target_date=self.primary_date_str,
            station=station,
        )

    def _load_cosmic_ray(self, params: dict[str, Any] | None = None):
        out_dir = os.path.join(self.date_dir, "nmdb")
        os.makedirs(out_dir, exist_ok=True)

        target_date = datetime.strptime(self.primary_date_str, "%Y-%m-%d")
        start_date = target_date - timedelta(days=15)
        end_date = target_date + timedelta(days=15)

        NmdbDownloader(out_dir=out_dir).download(
            start=start_date,
            end=end_date,
            stations=None,
        )

        return NmdbProcessor(folder_path=out_dir).load(self.primary_date_str)

    def _aurora_stub(self, date_str: str) -> pd.DataFrame:
        download_dir = self.date_dir
        os.makedirs(download_dir, exist_ok=True)

        h5_path = os.path.join(download_dir, "spaceweather_observations.h5")
        csv_path = os.path.join(download_dir, "aurora_data.csv")

        observations: list[dict[str, str]] = []
        storage = ObservationHDF5Storage(h5_path)

        date_iso = date_str
        date_slash = date_str.replace("-", "/")

        cached_rows = load_observations_from_csv(csv_path, date_iso)
        if cached_rows:
            observations.extend(cached_rows)

        if storage.has_date(date_iso):
            observations.extend(
                parse_and_save_observations(
                    h5_path,
                    csv_path,
                    dates=[date_iso],
                )
            )

        collect_observation_links(date_slash, h5_path)

        observations.extend(
            parse_and_save_observations(
                h5_path,
                csv_path,
                dates=[date_iso],
            )
        )

        if not observations:
            return pd.DataFrame(columns=["date", "time", "lat", "lon", "colors"])

        return pd.DataFrame(observations)

    def load_for_requested_plots(self, plots: list[str | dict[str, Any]]) -> dict[str, Any]:
        names = {
            self._normalize(item if isinstance(item, str) else item.get("name", ""))
            for item in plots
        }
        params_by_plot = self._merge_plot_params(plots)

        results: dict[str, Any] = {}

        if self._contains(names, "kp"):
            results["Kp"] = self._load_kp()

        if self._contains(names, "dst"):
            results["Dst"] = self._load_dst()

        if self._contains(names, "roti", "keogram"):
            results["ROTI"] = self._load_roti(params_by_plot.get("roti"))

        if self._contains(names, "adjusted tec", "tec adjusted"):
            results["Adjusted TEC"] = self._load_adjusted_tec(
                params_by_plot.get("adjusted tec")
                or params_by_plot.get("tec adjusted")
            )

        if self._contains(names, "gim"):
            results["GIM"] = self._load_gim(params_by_plot.get("gim"))

        if self._contains(names, "aurora observation", "aurora"):
            results["Aurora Observation"] = self._aurora_stub(self.primary_date_str)

        if self._contains(names, "ionosonde"):
            results["Ionosonde"] = self._load_ionosonde(params_by_plot.get("ionosonde"))

        if self._contains(names, "cosmic ray", "cosmic rays", "cosmic"):
            results["Cosmic Ray"] = self._load_cosmic_ray(
                params_by_plot.get("cosmic ray")
                or params_by_plot.get("cosmic rays")
            )

        return results