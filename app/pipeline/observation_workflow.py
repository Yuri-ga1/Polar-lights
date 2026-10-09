from __future__ import annotations

import os
from datetime import datetime, date
import csv
from typing import Dict, List, Literal

from app.visualization.aurora_map_plotter import AuroraMapPlotter, find_peak_aurora_time


from app.observation.aurorasaurus_loader import fetch_and_process_aurorasaurus
from app.observation.observation_links_finder import ObservationLinksFinder
from app.observation.observation_parser import ObservationParser
from app.observation.observation_processor import ObservationProcessor
from app.storage.hdf5_storage import ObservationHDF5Storage
from app.storage.data_paths import DataPaths

from app.logging_config import get_logger, logged_stage

logger = get_logger(__name__)

ObservationSource = Literal["aurorasaurus", "spaceweatherlive"]

# ---------------------------------------------------------------------------
# Helper function
# ---------------------------------------------------------------------------


def load_observations_from_csv(csv_path: str, date_iso: str) -> List[Dict[str, str]]:
    """Load observation records for a specific date from a CSV file.

    This helper reads the project's CSV of processed observations and returns
    rows matching the provided ISO formatted date string (``YYYY-MM-DD``).
    Each row is returned as a dictionary with string values, reflecting the
    original CSV contents.

    Parameters
    ----------
    csv_path : str
        Path to the CSV file of existing observations.  If the file does not
        exist, an empty list is returned.
    date_iso : str
        ISO formatted date (``YYYY-MM-DD``) to filter the rows by.

    Returns
    -------
    list of dict
        A list of observation rows for the given date.  If no matching rows
        are found or the file does not exist, an empty list is returned.
    """
    if not os.path.exists(csv_path):
        return []
    observations: List[Dict[str, str]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("date") == date_iso:
                observations.append(row)
    return observations


@logged_stage("pipeline", entry=True)
def run_observation_workflow(
    date: date,
    download_dir: str = "files",
    plots_dir: str = "results",
    plot_time: datetime | None = None,
    map_projection: str | None = None,
    map_focus: str | None = "europe",
    map_extent: tuple[float, float, float, float] | list[float] | None = None,
    source: ObservationSource = "aurorasaurus",
) -> list[dict[str, str]]:
    """Run the observation workflow for a single date.

    This function orchestrates fetching auroral observations, caching
    them in CSV format and producing a visualisation.  The ``source``
    parameter selects either the live SpaceWeatherLive observations or
    the Aurorasaurus dataset.

    Parameters
    ----------
    date : datetime.date
        The date for which observations should be fetched and plotted.
    download_dir : str, optional
        Directory where intermediate files (CSV and HDF5) will be saved.
    plots_dir : str, optional
        Directory where the resulting map image will be saved.
    plot_time : datetime or None, optional
        Specific time to display on the map.  If ``None``, a default
        timestamp is used.
    map_focus : {"europe", "america"} or None, optional
        Named map focus. ``None`` keeps the full world extent.
    map_extent : tuple or list of four floats, optional
        Custom ``(lon_min, lon_max, lat_min, lat_max)`` extent. Overrides
        ``map_focus`` when provided.
    source : {"aurorasaurus", "spaceweatherlive"}, optional
        Observation source.  Defaults to ``"aurorasaurus"``.

    Returns
    -------
    list of dict
        A list of observation records included in the CSV for the given date.
    """

    paths = DataPaths.from_root(download_dir)
    os.makedirs(plots_dir, exist_ok=True)

    if source not in {"aurorasaurus", "spaceweatherlive"}:
        raise ValueError("source must be 'aurorasaurus' or 'spaceweatherlive'")

    # Both providers share one normalized cache and the same map.
    csv_path = str(paths.processed_file("aurora_data"))

    observations: list[dict[str, str]] = []

    date_iso = date.strftime("%Y-%m-%d")

    # Load any previously cached observations from the CSV file.
    cached_rows = load_observations_from_csv(csv_path, date_iso)
    if cached_rows:
        observations.extend(cached_rows)

    aurora_rows: list[dict[str, str]] = []
    if not cached_rows:
        providers = (
            lambda: fetch_and_process_aurorasaurus(
                date,
                csv_path,
                download_dir=str(paths.raw_source("aurora")),
                auto_download=True,
            ),
            lambda: _fetch_spaceweatherlive(
                date, csv_path, str(paths.raw_source("aurora"))
            ),
        )
        for acquire in providers:
            try:
                aurora_rows.extend(acquire())
            except Exception as exc:  # noqa: BLE001 — continue with the other provider
                logger.warning(f"Aurora provider acquisition failed for {date_iso}: {exc}", extra={"event": "data_quality_warning"})
    observations.extend(aurora_rows)

    # If no CSV exists after processing, report and return early.
    if not os.path.exists(csv_path):
        logger.warning(f"File {csv_path} was not created because there is no observation", extra={"event": "data_quality_warning"})
        return []

    save_path = os.path.join(plots_dir, "Observation_map.png")
    plotter = AuroraMapPlotter(
        csv_path=csv_path,
        save_path=save_path,
        show_geomagnetic_equator=True,
        show_terminator=True,
        map_projection=map_projection,
        map_focus=map_focus,
        map_extent=map_extent,
    )

    resolved_plot_time = plot_time or find_peak_aurora_time(
        plotter.df,
        date,
    )

    plotter.plot(
        time=resolved_plot_time,
    )

    return observations


def _fetch_spaceweatherlive(
    day: date, csv_path: str, download_dir: str
) -> list[dict[str, str]]:
    """Fetch, parse and cache the observations from SpaceWeatherLive."""
    h5_path = os.path.join(download_dir, "spaceweather_observations.h5")
    date_iso = day.isoformat()
    date_slash = day.strftime("%Y/%m/%d")
    storage = ObservationHDF5Storage(h5_path)
    finder = ObservationLinksFinder()
    parser = ObservationParser()
    processor = ObservationProcessor(save_path=csv_path)
    try:
        links = finder.get_observation_links(date_slash)
        storage.save_links(date_iso, links)
        rows: list[dict[str, str]] = []
        for link in links:
            try:
                row = processor.process(parser.parse(link), persist=False)
            except (RuntimeError, ValueError, KeyError) as exc:
                logger.warning(
                    f"SpaceWeatherLive: skipping malformed observation at {link}: {exc}"
                , extra={"event": "data_quality_warning"})
                continue
            if row.get("date") == date_iso:
                processor.to_csv(row)
                rows.append(row)
        return rows
    finally:
        finder.close()
