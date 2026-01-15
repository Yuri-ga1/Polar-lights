from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable

from app.pipeline.observation_pipeline import (
    collect_observation_links,
    load_observations_from_csv,
    parse_and_save_observations,
)
from app.storage.hdf5_storage import ObservationHDF5Storage
from app.visualization.aurora_map_plotter import AuroraMapPlotter


def run_observation_workflow(
    dates: Iterable[datetime],
    base_out_dir: str = "files",
    plot_time: datetime | None = None,
) -> list[dict[str, str]]:
    dates = list(dates)

    h5_path = os.path.join(base_out_dir, "spaceweather_observations.h5")
    csv_path = os.path.join(base_out_dir, "aurora_data.csv")

    observations: list[dict[str, str]] = []
    storage = ObservationHDF5Storage(h5_path)

    for date in dates:
        date_str = date.strftime("%Y/%m/%d")
        date_iso = date.strftime("%Y-%m-%d")

        cached_rows = load_observations_from_csv(csv_path, date_iso)
        if cached_rows:
            observations.extend(cached_rows)
            continue

        if storage.has_date(date_iso):
            observations.extend(
                parse_and_save_observations(
                    h5_path,
                    csv_path,
                    dates=[date_iso],
                )
            )
            continue

        collect_observation_links(date_str, h5_path)
        observations.extend(
            parse_and_save_observations(
                h5_path,
                csv_path,
                dates=[date_iso],
            )
        )

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

    return observations
