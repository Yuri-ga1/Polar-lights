from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any
from datetime import datetime, timedelta

import pandas as pd

from app.observation.aurorasaurus_loader import fetch_and_process_aurorasaurus

from app.gfz.gfz_downloader import GfzDownloader
from app.gfz.gfz_processor import GfzProcessor

from app.kyoto.kyoto_dst_downloader import KyotoDstDownloader
from app.kyoto.kyoto_dst_processor import KyotoProcessor

from app.simurg.gim_downloader import GimDownloader
from app.simurg.gim_processor import GimProcessor

from app.simurg.simurg_client import SimurgClient
from app.simurg.simurg_downloader import RotiDownloader, AdjustedTecDownloader
from app.simurg.simurg_processor import SimurgProcessor, DataProduct
from app.visualization.keogram_plotter import (
    KeogramConfig,
    KeogramData,
    build_keogram_matrix_from_slices,
    resolve_keogram_times,
)

from app.ionosonde.ionosonde_downloader import IonosondeDownloader
from app.ionosonde.ionosonde_processor import IonosondeProcessor

from app.nmdb.nmdb_downloader import NmdbDownloader
from app.nmdb.nmdb_processor import NmdbProcessor

from app.omni.omni_downloader import OmniDownloader
from app.omni.omni_processor import OmniProcessor


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
    
    @classmethod
    def _parse_plot_time(cls, value: Any) -> datetime:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)

        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime().replace(tzinfo=None)

        if isinstance(value, str):
            return cls._parse_datetime(value)

        raise ValueError(
            f"Unsupported map time value type: {type(value)!r}. "
            "Use YYYY-MM-DD HH:MM:SS."
        )

    @classmethod
    def _iter_plot_times(cls, raw_time: Any) -> list[datetime]:
        if raw_time is None:
            return []

        if isinstance(raw_time, (list, tuple, set)):
            return [cls._parse_plot_time(item) for item in raw_time]

        return [cls._parse_plot_time(raw_time)]

    def _validate_map_times_in_range(
        self,
        plots: list[str | dict[str, Any]],
    ) -> None:
        for item in plots:
            if isinstance(item, str):
                continue

            name = self._normalize(str(item.get("name", "")))
            params = dict(item.get("params", {}))

            if not self._contains(
                {name},
                "roti",
                "gim",
                "adjusted tec",
                "tec adjusted",
                "aurora observation",
                "aurora",
                "keogram",
            ):
                continue

            plot_times = self._iter_plot_times(params.get("time"))

            for plot_time in plot_times:
                if self.start_dt <= plot_time <= self.end_dt:
                    continue

                raise ValueError(
                    f"Map time '{plot_time:%Y-%m-%d %H:%M:%S}' for plot "
                    f"'{item.get('name')}' is outside the selected range: "
                    f"{self.start_dt:%Y-%m-%d %H:%M:%S} — "
                    f"{self.end_dt:%Y-%m-%d %H:%M:%S}."
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
        
    @classmethod
    def _collect_group_fields(cls, plots: list[str | dict[str, Any]]) -> set[str]:
        fields: set[str] = set()

        for item in plots:
            if isinstance(item, str):
                continue

            params = dict(item.get("params", {}))
            groups = params.get("groups") or []

            for group in groups:
                for field in group.get("fields", []):
                    fields.add(cls._normalize(str(field)))

        return fields
    
    def _filter_by_datetime_range(self, df: pd.DataFrame | None) -> pd.DataFrame | None:
        if df is None or df.empty:
            return df

        if "datetime" not in df.columns:
            return df

        time_values = pd.to_datetime(df["datetime"], errors="coerce")
        mask = (time_values >= self.start_dt) & (time_values <= self.end_dt)

        return df.loc[mask].reset_index(drop=True)

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

        kp_df = GfzProcessor(folder_path=out_dir).load(date_str=self.primary_date_str)
        return self._filter_by_datetime_range(kp_df)

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

    def _load_keogram(self, params: dict[str, Any] | None = None):
        params = params or {}

        client = self._simurg_client(params.get("email"))
        if client is None:
            print("SIMURG email is missing, skip ROTI keogram download")
            return None

        out_dir = os.path.join(self.date_dir, "simurg")
        os.makedirs(out_dir, exist_ok=True)

        self._safe_download(
            lambda: RotiDownloader(client=client, out_dir=out_dir).download(
                self.primary_date_str
            )
        )

        cfg = KeogramConfig(
            lat_step_deg=float(params.get("lat_step_deg", KeogramConfig.lat_step_deg)),
            time_step_min=int(params.get("time_step_min", KeogramConfig.time_step_min)),
            hour_min=int(params.get("hour_min", KeogramConfig.hour_min)),
            hour_max=int(params.get("hour_max", KeogramConfig.hour_max)),
            hemisphere=params.get("hemisphere", KeogramConfig.hemisphere),
            cmap=params.get("cmap", KeogramConfig.cmap),
            vmin=float(params.get("vmin", KeogramConfig.vmin)),
            vmax=float(params.get("vmax", KeogramConfig.vmax)),
            colorbar_label=params.get("colorbar_label", KeogramConfig.colorbar_label),
        )

        target_date = datetime.strptime(self.primary_date_str, "%Y-%m-%d").date() - timedelta(days=1)
        processor = SimurgProcessor(folder_path=out_dir)
        available_times = processor.available_times(
            target_date,
            product_type=DataProduct.ROTI,
        )
        if not available_times:
            return None

        day_start = self.start_dt.date()
        day_finish = self.end_dt.date()
        keogram_times = resolve_keogram_times(available_times, day_start, day_finish, cfg)

        matrix, times, lat_centers = build_keogram_matrix_from_slices(
            time_slices=processor.iter_slices(
                target_date,
                product_type=DataProduct.ROTI,
                times=keogram_times,
            ),
            available_times=available_times,
            day_start=day_start,
            day_finish=day_finish,
            cfg=cfg,
        )

        return KeogramData(
            matrix=matrix,
            times=times,
            lat_centers=lat_centers,
            cfg=cfg,
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

    def _load_omni(self):
        out_dir = os.path.join(self.date_dir, "omni")
        os.makedirs(out_dir, exist_ok=True)

        for date_str in self.download_dates:
            self._safe_download(
                lambda d=date_str: OmniDownloader(out_dir=out_dir).download(d)
            )

        return OmniProcessor(folder_path=out_dir).load(self.primary_date_str)

    def _aurora_stub(self, date_str: str | None = None) -> pd.DataFrame:
        """
        Load aurora observations for the full constructor date range.

        For PlotConstructor we need all complete calendar days included in
        DATE_START — DATE_END, not only the first date.
        """
        out_dir = os.path.join(self.date_dir, "aurora")
        os.makedirs(out_dir, exist_ok=True)

        csv_path = os.path.join(out_dir, "aurora_data.csv")

        expected_columns = [
            "date",
            "time",
            "duration_min",
            "lat",
            "lon",
            "forms",
            "colors",
        ]

        def empty_observations_df() -> pd.DataFrame:
            return pd.DataFrame(columns=expected_columns)

        def normalize_observations_df(df: pd.DataFrame) -> pd.DataFrame:
            if df is None or df.empty:
                return empty_observations_df()

            df = df.copy()

            for column in expected_columns:
                if column not in df.columns:
                    df[column] = ""

            df = df[expected_columns].copy()

            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
            df["time"] = df["time"].fillna("").astype(str)

            df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
            df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
            df["duration_min"] = pd.to_numeric(df["duration_min"], errors="coerce")

            df["forms"] = df["forms"].fillna("").astype(str)
            df["colors"] = (
                df["colors"]
                .fillna("")
                .astype(str)
                .str.replace(",", ";", regex=False)
                .str.strip()
            )

            df = df[
                df["date"].isin(self.download_dates)
                & df["lat"].notna()
                & df["lon"].notna()
            ].copy()

            if df.empty:
                return empty_observations_df()

            df = df.drop_duplicates(
                subset=["date", "time", "lat", "lon", "forms", "colors"],
                keep="first",
            ).reset_index(drop=True)

            return df

        all_rows: list[dict[str, Any]] = []

        for current_date_str in self.download_dates:
            target_date = datetime.strptime(current_date_str, "%Y-%m-%d").date()

            rows = self._safe_download(
                lambda d=target_date: fetch_and_process_aurorasaurus(
                    d,
                    csv_path,
                    download_dir=out_dir,
                    auto_download=True,
                )
            )

            if rows:
                all_rows.extend(rows)

        if all_rows:
            return normalize_observations_df(pd.DataFrame(all_rows))

        if os.path.exists(csv_path):
            return normalize_observations_df(pd.read_csv(csv_path))

        print(
            "No aurora observations found for date range: "
            f"{self.download_dates[0]} — {self.download_dates[-1]}"
        )
        return empty_observations_df()

    def load_for_requested_plots(self, plots: list[str | dict[str, Any]]) -> dict[str, Any]:
        self._validate_map_times_in_range(plots)
        
        names = {
            self._normalize(item if isinstance(item, str) else item.get("name", ""))
            for item in plots
        }
        params_by_plot = self._merge_plot_params(plots)
        group_fields = self._collect_group_fields(plots)

        results: dict[str, Any] = {}

        if self._contains(names, "kp"):
            results["Kp"] = self._load_kp()

        if self._contains(names, "dst") or "dst" in group_fields:
            results["Dst"] = self._load_dst()

        if self._contains(names, "roti"):
            results["ROTI"] = self._load_roti(params_by_plot.get("roti"))

        if self._contains(names, "keogram"):
            results["Keogram"] = self._load_keogram(params_by_plot.get("keogram"))

        if self._contains(names, "adjusted tec", "tec adjusted"):
            results["Adjusted TEC"] = self._load_adjusted_tec(
                params_by_plot.get("adjusted tec")
                or params_by_plot.get("tec adjusted")
            )

        if self._contains(names, "gim"):
            results["GIM"] = self._load_gim(params_by_plot.get("gim"))

        if self._contains(names, "aurora observation", "aurora"):
            results["Aurora Observation"] = self._aurora_stub()

        if self._contains(names, "ionosonde"):
            results["Ionosonde"] = self._load_ionosonde(params_by_plot.get("ionosonde"))

        if self._contains(names, "cosmic ray", "cosmic rays", "cosmic"):
            results["Cosmic Ray"] = self._load_cosmic_ray(
                params_by_plot.get("cosmic ray")
                or params_by_plot.get("cosmic rays")
            )

        if self._contains(names, "omni"):
            results["OMNI"] = self._load_omni()

        return results
