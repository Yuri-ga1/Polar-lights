import os
from datetime import datetime

from app.visualization.aurora_map_plotter import AuroraMapPlotter
from app.pipeline.observation_pipeline import (
    collect_observation_links,
    parse_and_save_observations
)


if __name__ == "__main__":
    dates = ["2025/11/12", "2025/11/13"]
    h5_path = os.path.join("files", "spaceweather_observations.h5")
    csv_path =  os.path.join("files", "aurora_data.csv")

    collect_observation_links(dates, h5_path)
    parse_and_save_observations(h5_path, csv_path)

    save_path = os.path.join('files', 'obs_map.png')
    plotter = AuroraMapPlotter(
        csv_path=csv_path,
        save_path=save_path,
        show_geomagnetic_equator=True,
        show_terminator=True
    )

    plotter.plot(
        time=datetime(2025, 11, 12, 2, 0)
    )