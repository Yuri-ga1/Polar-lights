from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Sequence

from app.gfz.gfz_processor import GfzProcessor
from app.ionosonde.ionosonde_downloader import IonosondeDownloader
from app.ionosonde.ionosonde_processor import IonosondeProcessor
from app.nmdb.nmdb_downloader import NmdbDownloader
from app.nmdb.nmdb_processor import NmdbProcessor
from app.pipeline.space_weather_pipeline import prepare_space_weather_data
from app.simurg.gim_downloader import GimDownloader
from app.simurg.gim_processor import GimProcessor
from app.visualization.cosmic_ray_plotter import plot_cosmic_ray_variations
from app.visualization.gim_plotter import plot_gim_maps
from app.visualization.ionosonde_plotter import plot_ionosonde
from app.visualization.solar_and_indexes_plotter import plot_sw_symh_dst_kp

logger = logging.getLogger(__name__)


def _pick_plot_times(data: dict[datetime, object], max_plots: int = 4) -> list[datetime]:
    if not data:
        return []

    sorted_times = sorted(data.keys())
    if len(sorted_times) <= max_plots:
        return sorted_times

    step = max(1, len(sorted_times) // max_plots)
    selected = sorted_times[::step][:max_plots]
    if sorted_times[-1] not in selected:
        selected[-1] = sorted_times[-1]
    return selected


def _resolve_cosmic_stations(
    cr_df,
    requested_stations: Sequence[str] | None,
    fallback_count: int = 3,
) -> list[str]:
    station_columns = [column for column in cr_df.columns if column != "datetime"]
    if not station_columns:
        return []

    if requested_stations:
        requested_available = [station for station in requested_stations if station in station_columns]
        if requested_available:
            return requested_available
        logger.warning("Запрошенные станции не найдены в данных NMDB: %s", list(requested_stations))

    return station_columns[:fallback_count]


def run_misc_pipeline(
    date_str: str,
    download_dir: str,
    plots_dir: str,
    ionosonde_code: str | None,
    cosmic_stations: Sequence[str] | None,
) -> None:
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(plots_dir, exist_ok=True)

    sw_data = prepare_space_weather_data(date_str=date_str, download_dir=download_dir)

    if sw_data.omni is not None and sw_data.dst is not None and sw_data.kp is not None:
        plot_sw_symh_dst_kp(sw_df=sw_data.omni, dst_df=sw_data.dst, kp_df=sw_data.kp, save_dir=plots_dir)

    gim_dir = os.path.join(download_dir, "gim")
    os.makedirs(gim_dir, exist_ok=True)
    GimDownloader(out_dir=gim_dir).download(date_str)
    gim_data = GimProcessor(folder_path=gim_dir).load(date_str)
    if gim_data:
        plot_gim_maps(data=gim_data, plot_times=_pick_plot_times(gim_data), save_dir=plots_dir)

    ionosonde_dir = os.path.join(download_dir, "ionosonde")
    os.makedirs(ionosonde_dir, exist_ok=True)
    IonosondeDownloader(out_dir=ionosonde_dir).download(target_date=date_str, station=ionosonde_code)
    ionosonde_df = IonosondeProcessor(folder_path=ionosonde_dir).load(
        target_date=date_str,
        station=ionosonde_code,
    )
    if ionosonde_df is not None and not ionosonde_df.empty:
        plot_ionosonde(ionosonde_df, save_dir=plots_dir)

    nmdb_dir = os.path.join(download_dir, "nmdb")
    os.makedirs(nmdb_dir, exist_ok=True)
    target_date = datetime.strptime(date_str, "%Y-%m-%d")
    start_date = target_date - timedelta(days=15)
    end_date = target_date + timedelta(days=15)
    NmdbDownloader(out_dir=nmdb_dir).download(
        start=start_date,
        end=end_date,
        stations=cosmic_stations,
    )

    cr_df = NmdbProcessor(folder_path=nmdb_dir).load(date_str)
    kp_df = GfzProcessor(folder_path=os.path.join(download_dir, "kp")).load(date_str=date_str)
    if cr_df is not None and not cr_df.empty and kp_df is not None and not kp_df.empty:
        stations_for_plot = _resolve_cosmic_stations(cr_df, cosmic_stations)
        if stations_for_plot:
            plot_cosmic_ray_variations(cr_df=cr_df, kp_df=kp_df, stations=stations_for_plot, save_dir=plots_dir)
