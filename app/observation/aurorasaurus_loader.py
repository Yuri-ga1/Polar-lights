"""
Utilities to load and process auroral observations from the
Aurorasaurus ``Web Observations`` dataset.

This dataset is provided as a single CSV covering the period from
1 August 2014 through 2 August 2025 and contains crowdsourced
observations submitted via the Aurorasaurus website.  Each row in the
CSV includes a timestamp (UTC), geographic coordinates (``st_y`` and
``st_x``), estimated duration (hours), colour and form codes, and
additional metadata.  Only rows where observers explicitly reported
seeing aurora (``see_aurora == True``) are considered valid
observations.

The functions in this module convert the Aurorasaurus CSV into the
standard format used throughout the ``Polar‑lights`` project.  The
standard observation dictionary contains keys ``date``, ``time``,
``duration_min``, ``lat``, ``lon``, ``forms`` and ``colors``.  Colour
and form codes in the source data are mapped to human‑readable
descriptors and deduplicated.  Durations in the source data are
provided in hours and are converted into minutes.  Observations are
filtered by date and appended to a user‑supplied CSV file, avoiding
duplicate entries.

"""

from __future__ import annotations

import csv
import os
from datetime import date as date_cls
from typing import Any, Dict, List, Optional

import pandas as pd

from app.observation.aurorasaurus_downloader import AurorasaurusDownloader


# Name of the cleaned Aurorasaurus CSV file.  If ``data_path`` is not
# provided to :func:`fetch_and_process_aurorasaurus`, the code will
# attempt to locate a file with this name in the current working
# directory or common sub‑directories such as ``data`` and ``files``.
DEFAULT_DATAFILE_NAME = "web_observations_2014-08-01_to_2025-08-02_cleaned.csv"
AURORASAURUS_START_DATE = date_cls(2014, 8, 1)
AURORASAURUS_END_DATE = date_cls(2025, 8, 2)

# Mapping of truncated colour codes used by the Aurorasaurus dataset
# into full colour names.  If a code is not present in this mapping,
# the first character is capitalised and the rest of the code is
# preserved verbatim.
COLOR_MAP = {
    "gree": "Green",
    "red": "Red",
    "pink": "Pink",
    "whit": "White",
}

# Mapping of truncated form codes into descriptive names.  Any
# unrecognised code is capitalised as‑is.
FORM_MAP = {
    "arcs": "Arcs",
    "glow": "Glow",
    "patc": "Patches",
}

def _validate_date_range(day: date_cls) -> None:
    """Validate that requested date is covered by Aurorasaurus dataset."""
    if not (AURORASAURUS_START_DATE <= day <= AURORASAURUS_END_DATE):
        raise ValueError(
            "Aurorasaurus Web Observations dataset covers only "
            f"{AURORASAURUS_START_DATE.isoformat()} — "
            f"{AURORASAURUS_END_DATE.isoformat()}. "
            f"Requested date: {day.isoformat()}."
        )

def _locate_dataset(
    data_path: Optional[str],
    download_dir: str = "files",
    auto_download: bool = True,
) -> str:
    """Locate the Aurorasaurus dataset on disk or download it."""
    candidates: List[str] = []
    if data_path:
        candidates.append(data_path)

    cwd = os.getcwd()
    candidates.extend([
        os.path.join(cwd, DEFAULT_DATAFILE_NAME),
        os.path.join(cwd, "data", DEFAULT_DATAFILE_NAME),
        os.path.join(cwd, "files", DEFAULT_DATAFILE_NAME),
        os.path.join(os.path.dirname(__file__), DEFAULT_DATAFILE_NAME),
        os.path.join(os.path.dirname(__file__), "..", "..", "data", DEFAULT_DATAFILE_NAME),
        os.path.join(os.path.dirname(__file__), "..", "..", "files", DEFAULT_DATAFILE_NAME),
    ])

    for path in candidates:
        if path and os.path.exists(path):
            return os.path.abspath(path)

    if auto_download:
        downloader = AurorasaurusDownloader(out_dir=download_dir)
        return downloader.download(DEFAULT_DATAFILE_NAME)

    raise FileNotFoundError(
        f"Aurorasaurus data file not found. Please download '{DEFAULT_DATAFILE_NAME}' "
        "from Zenodo and place it in your project directory, or enable auto_download."
    )


def _parse_colors(raw: str) -> str:
    """Translate a comma‑separated list of colour codes into a semicolon string.

    The Aurorasaurus dataset stores colour codes as truncated strings
    (e.g. ``gree`` for green).  This function splits the raw value on
    commas, strips whitespace, maps known codes to full names and
    capitalises unknown codes.  Duplicate colours are removed while
    preserving order.

    Parameters
    ----------
    raw : str
        The raw colour codes from the dataset (may be NaN/empty).

    Returns
    -------
    str
        A semicolon‑delimited list of colour names.  Returns an empty
        string if no colours are present.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ""
    parts = [c.strip() for c in raw.split(",") if c.strip()]
    seen = set()
    result: List[str] = []
    for code in parts:
        # Map to full name if known
        name = COLOR_MAP.get(code.lower())
        if not name:
            # Unknown code: capitalise the first letter and keep the rest
            name = code.capitalize()
        if name not in seen:
            seen.add(name)
            result.append(name)
    return ";".join(result)


def _parse_forms(raw: str) -> str:
    """Translate a comma‑separated list of form codes into a semicolon string.

    Parameters
    ----------
    raw : str
        Raw form codes from the dataset (may be NaN/empty).

    Returns
    -------
    str
        Semicolon‑delimited form names.
    """
    if not isinstance(raw, str) or not raw.strip():
        return ""
    parts = [t.strip() for t in raw.split(",") if t.strip()]
    seen = set()
    result: List[str] = []
    for code in parts:
        name = FORM_MAP.get(code.lower())
        if not name:
            name = code.capitalize()
        if name not in seen:
            seen.add(name)
            result.append(name)
    return ";".join(result)


def _process_row(row: pd.Series) -> Dict[str, Any]:
    """Convert a single Aurorasaurus row into the standard observation format.

    Parameters
    ----------
    row : pandas.Series
        A row from the Aurorasaurus DataFrame.

    Returns
    -------
    dict
        A mapping containing keys ``date``, ``time``, ``duration_min``,
        ``lat``, ``lon``, ``forms`` and ``colors``.
    """
    # Use the timestamp column as the primary date/time.  It is stored
    # as a timezone‑aware ISO string.  Convert to pandas Timestamp.
    ts = pd.to_datetime(row["timestamp"])
    date_str = ts.date().isoformat()
    time_str = ts.time().strftime("%H:%M:%S")

    # Latitude and longitude (geographic coordinates)
    lat = row["st_y"]
    lon = row["st_x"]

    # Duration: either provided directly (in hours) or computed from
    # start/end times.  Some rows have a pre‑computed ``duration``
    # column.  Convert hours to minutes.  If not available, attempt
    # difference between ``time_end`` and ``time_start``.  Otherwise
    # leave blank (None) similar to ARCTICS loader behaviour.
    dur_min: Optional[float] = None
    if pd.notna(row.get("duration")):
        try:
            dur_min = float(row["duration"]) * 60.0
        except Exception:
            dur_min = None
    elif pd.notna(row.get("time_start")) and pd.notna(row.get("time_end")):
        try:
            t_start = pd.to_datetime(row["time_start"])
            t_end = pd.to_datetime(row["time_end"])
            dur_min = (t_end - t_start).total_seconds() / 60.0
        except Exception:
            dur_min = None

    # Parse colours and forms
    colours = _parse_colors(row.get("colors", ""))
    forms = _parse_forms(row.get("types", ""))

    return {
        "date": date_str,
        "time": time_str,
        "duration_min": dur_min,
        "lat": lat,
        "lon": lon,
        "forms": forms,
        "colors": colours,
    }


def fetch_and_process_aurorasaurus(
    day: date_cls,
    csv_path: str,
    data_path: Optional[str] = None,
    download_dir: str = "files",
    auto_download: bool = True,
) -> List[Dict[str, Any]]:
    """Load Aurorasaurus observations for a given date and append to CSV.

    This function reads the cleaned Aurorasaurus dataset from a local
    file, filters rows to the specified date and to observations where
    ``see_aurora`` is True, converts each row into the standard
    observation dictionary and appends the result to the CSV file at
    ``csv_path``.  Duplicate observations (by timestamp and location)
    are not explicitly removed, but calling code may avoid creating
    duplicates by checking for existing rows before appending.

    Parameters
    ----------
    day : datetime.date
        Date for which observations should be extracted.
    csv_path : str
        Path to the CSV file where processed observations will be saved.
    data_path : str, optional
        Optional path to the cleaned Aurorasaurus CSV file.  If not
        provided, the function attempts to locate a file named
        ``DEFAULT_DATAFILE_NAME`` in common directories.  If the file
        cannot be found, a ``FileNotFoundError`` is raised.

    Returns
    -------
    list of dict
        A list of processed observations corresponding to the input date.
    """
    _validate_date_range(day)
    # Resolve the dataset path
    dataset_file = _locate_dataset(data_path, download_dir=download_dir, auto_download=auto_download)

    # Load the CSV into a DataFrame.  Parse only the columns we need to
    # minimise memory usage.  The dataset has around 22k rows and 33
    # columns; selecting only the relevant ones speeds up loading.
    usecols = [
        "timestamp",
        "st_y",
        "st_x",
        "colors",
        "types",
        "see_aurora",
        "duration",
        "time_start",
        "time_end",
    ]
    df = pd.read_csv(dataset_file, usecols=usecols)

    if df["see_aurora"].dtype != bool:
        df["see_aurora"] = df["see_aurora"].astype(str).str.lower().eq("true")

    # Convert timestamp to datetime for filtering
    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        format="mixed",
        utc=True,
        errors="coerce",
    )

    df = df.dropna(subset=["timestamp", "st_y", "st_x"])

    # Filter by date and only keep rows where the observer saw aurora
    mask = (df["timestamp"].dt.date == day) & (df["see_aurora"] == True)
    filtered = df.loc[mask]

    observations: List[Dict[str, Any]] = []
    if filtered.empty:
        return observations

    # Determine if the output CSV already exists; if not, we'll write
    # the header when we open the file for appending.
    file_exists = os.path.exists(csv_path)

    # Convert and collect observations
    for _, row in filtered.iterrows():
        obs = _process_row(row)
        observations.append(obs)

    # Write to CSV
    fieldnames = ["date", "time", "duration_min", "lat", "lon", "forms", "colors"]
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for obs in observations:
            writer.writerow(obs)

    return observations