from __future__ import annotations

import os
from datetime import datetime, date
import csv
from typing import Dict, List, Literal

from app.visualization.aurora_map_plotter import AuroraMapPlotter


from app.observation.aurorasaurus_loader import fetch_and_process_aurorasaurus
from app.observation.observation_links_finder import ObservationLinksFinder
from app.observation.observation_parser import ObservationParser
from app.observation.observation_processor import ObservationProcessor
from app.storage.hdf5_storage import ObservationHDF5Storage

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


def run_observation_workflow(
    date: date,
    download_dir: str = "files",
    plots_dir: str = "results",
    plot_time: datetime | None = None,
    map_projection: str | None = None,
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
    source : {"aurorasaurus", "spaceweatherlive"}, optional
        Observation source.  Defaults to ``"aurorasaurus"``.

    Returns
    -------
    list of dict
        A list of observation records included in the CSV for the given date.
    """

    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(plots_dir, exist_ok=True)

    # Keep the source-specific CSVs independent when users switch providers.
    if source not in {"aurorasaurus", "spaceweatherlive"}:
        raise ValueError("source must be 'aurorasaurus' or 'spaceweatherlive'")

    # Keep source caches separate: otherwise changing the source would mix
    # observations from unrelated datasets in one map.
    csv_name = "aurora_data.csv" if source == "aurorasaurus" else "spaceweatherlive_aurora_data.csv"
    csv_path = os.path.join(download_dir, csv_name)

    observations: list[dict[str, str]] = []

    date_iso = date.strftime("%Y-%m-%d")

    # Load any previously cached observations from the CSV file.
    cached_rows = load_observations_from_csv(csv_path, date_iso)
    if cached_rows:
        observations.extend(cached_rows)

    if source == "aurorasaurus":
        aurora_rows = [] if cached_rows else fetch_and_process_aurorasaurus(
            date, csv_path, download_dir=download_dir, auto_download=True
        )
    else:
        aurora_rows = [] if cached_rows else _fetch_spaceweatherlive(
            date, csv_path, download_dir
        )
    observations.extend(aurora_rows)

    # If no CSV exists after processing, report and return early.
    if not os.path.exists(csv_path):
        print(f'File {csv_path} was not created because there is no observation')
        return []


    save_path = os.path.join(plots_dir, "Observation_map.png")
    plotter = AuroraMapPlotter(
        csv_path=csv_path,
        save_path=save_path,
        show_geomagnetic_equator=True,
        show_terminator=True,
        map_projection=map_projection,
    )

    plotter.plot(
        time=plot_time or datetime(2025, 4, 16, 22, 0),
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
                row = processor.process(parser.parse(link))
            except (RuntimeError, ValueError, KeyError) as exc:
                print(
                    f"SpaceWeatherLive: stopping observation downloads after "
                    f"failure at {link}: {exc}. Building the map from "
                    f"{len(rows)} already received observations."
                )
                break
            if row.get("date") == date_iso:
                rows.append(row)
        return rows
    finally:
        finder.close()
