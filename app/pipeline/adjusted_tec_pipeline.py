from __future__ import annotations

import logging
import os
from datetime import datetime

from app.simurg.simurg_client import SimurgClient
from app.simurg.simurg_downloader import AdjustedTecDownloader
from app.simurg.simurg_processor import DataProduct, SimurgProcessor
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


def run_adjusted_tec_pipeline(
    date_str: str,
    download_dir: str,
    plots_dir: str,
    simurg_client: SimurgClient | None,
) -> None:
    if simurg_client is None:
        logger.warning("SimurgClient не создан. Поток adjusted TEC пропущен.")
        return

    simurg_dir = os.path.join(download_dir, "simurg")
    os.makedirs(simurg_dir, exist_ok=True)
    os.makedirs(plots_dir, exist_ok=True)

    AdjustedTecDownloader(client=simurg_client, out_dir=simurg_dir).download(date_str)

    data = SimurgProcessor(folder_path=simurg_dir).load(
        date_str,
        product_type=DataProduct.TEC_ADJUSTED,
    )
    if not data:
        logger.warning("Не удалось загрузить данные adjusted TEC для %s.", date_str)
        return

    plot_map(data=data, plot_times=_pick_plot_times(data), product_type="tec_adjusted", save_dir=plots_dir)
