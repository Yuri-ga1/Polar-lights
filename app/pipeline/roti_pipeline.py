from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from app.simurg.simurg_client import SimurgClient
from app.simurg.simurg_downloader import RotiDownloader
from app.simurg.simurg_processor import DataProduct, SimurgProcessor
from app.visualization.keogram_plotter import (
    KeogramConfig,
    build_keogram_matrix_from_slices,
    plot_keogram_matrix,
    resolve_keogram_times,
)
from app.visualization.roti_plotter import plot_map

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


def run_roti_pipeline(
    date_str: str,
    download_dir: str,
    plots_dir: str,
    simurg_client: SimurgClient | None,
    map_projection: str | None = None,
) -> None:
    if simurg_client is None:
        logger.warning("SimurgClient is not configured. ROTI pipeline skipped.")
        return

    simurg_dir = os.path.join(download_dir, "simurg")
    os.makedirs(simurg_dir, exist_ok=True)
    os.makedirs(plots_dir, exist_ok=True)

    RotiDownloader(client=simurg_client, out_dir=simurg_dir).download(date_str)

    target_date = datetime.strptime(date_str, "%Y-%m-%d")
    file_start_date = (target_date - timedelta(days=1)).date()
    processor = SimurgProcessor(folder_path=simurg_dir)

    available_times = processor.available_times(
        file_start_date,
        product_type=DataProduct.ROTI,
    )
    if not available_times:
        logger.warning("Failed to load ROTI data for %s.", date_str)
        return

    plot_times = _pick_plot_times({plot_time: None for plot_time in available_times})
    map_data = processor.load(
        file_start_date,
        product_type=DataProduct.ROTI,
        times=plot_times,
    )
    if map_data:
        plot_map(
            data=map_data,
            plot_times=plot_times,
            product_type="roti",
            save_dir=plots_dir,
            map_projection=map_projection,
        )

    cfg = KeogramConfig()
    day_start = min(available_times).date()
    day_finish = max(available_times).date()
    keogram_times = resolve_keogram_times(available_times, day_start, day_finish, cfg)

    matrix, times, lat_centers = build_keogram_matrix_from_slices(
        time_slices=processor.iter_slices(
            file_start_date,
            product_type=DataProduct.ROTI,
            times=keogram_times,
        ),
        available_times=available_times,
        day_start=day_start,
        day_finish=day_finish,
        cfg=cfg,
    )
    plot_keogram_matrix(
        matrix=matrix,
        times=times,
        lat_centers=lat_centers,
        cfg=cfg,
        save_dir=plots_dir,
    )
