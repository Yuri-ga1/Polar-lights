from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from app.pipeline.observation_pipeline import (
    collect_observation_links,
    parse_and_save_observations,
)
from app.visualization.aurora_map_plotter import AuroraMapPlotter


def run_observation_workflow(
    dates: Iterable[datetime],
    base_out_dir: str = "files",
    plot_time: datetime | None = None,
) -> None:
    dates = list(dates)

    h5_path = os.path.join(base_out_dir, "spaceweather_observations.h5")
    csv_path = os.path.join(base_out_dir, "aurora_data.csv")

    for date in dates:
        date_str = date.strftime("%Y/%m/%d")
        collect_observation_links(date_str, h5_path)
        parse_and_save_observations(h5_path, csv_path)

    save_path = os.path.join(base_out_dir, "obs_map.png")
    plotter = AuroraMapPlotter(
        csv_path=csv_path,
        save_path=save_path,
        show_geomagnetic_equator=True,
        show_terminator=True,
    )

    plotter.plot(
        time=plot_time or datetime(2025, 11, 12, 2, 0),
    )