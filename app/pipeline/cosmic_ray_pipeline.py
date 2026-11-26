"""Cached data retrieval for the cosmic-ray plot and its Kp context."""

from datetime import timedelta

import pandas as pd

from app.gfz.gfz_processor import GfzProcessor
from app.nmdb.nmdb_processor import NmdbProcessor
from app.pipeline.space_weather_pipeline import SpaceWeatherPaths, _retrieve_kp
from app.storage.data_paths import DataPaths


def prepare_cosmic_ray_data_range(download_dir, start, end, stations=None):
    paths = DataPaths.from_root(download_dir)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    cr = NmdbProcessor(paths.raw_source("nmdb")).load_range(
        paths.processed_file("nmdb"), start, end, stations,
    )
    kp_processor = GfzProcessor(paths.raw_source("kp"))
    kp_processor.expected_frequency = timedelta(hours=3)
    weather_paths = SpaceWeatherPaths.from_base(str(paths.root))
    # Kp timestamps are on the UTC 00/03/06/... grid, regardless of plot start.
    kp = kp_processor.get_data(
        paths.processed_file("kp"), start.floor("3h"), end.floor("3h"),
        lambda gaps: _retrieve_kp(weather_paths, gaps[0][0], gaps[-1][1]),
    )
    return cr, kp_processor.with_datetime(kp)
