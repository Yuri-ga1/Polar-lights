import os
from typing import Iterable

import pandas as pd

from app.observation.observation_links_finder import ObservationLinksFinder
from app.observation.observation_parser import ObservationParser
from app.observation.observation_processor import ObservationProcessor
from app.storage.hdf5_storage import ObservationHDF5Storage


def collect_observation_links(date: str, h5_path: str):
    finder = ObservationLinksFinder()
    storage = ObservationHDF5Storage(h5_path)

    links = finder.get_observation_links(date)
    print(f"{date}: найдено {len(links)} наблюдений")
    storage.save_links(date, links)

def load_observations_from_csv(csv_path: str, date_iso: str) -> list[dict[str, str]]:
    if not os.path.isfile(csv_path):
        return []

    df = pd.read_csv(csv_path)
    if df.empty or "date" not in df.columns:
        return []

    filtered = df[df["date"] == date_iso]
    if filtered.empty:
        return []

    return filtered.fillna("").to_dict(orient="records")


def parse_and_save_observations(
    h5_path: str,
    csv_path: str,
    dates: Iterable[str] | None = None,
) -> list[dict[str, str]]:
    parser = ObservationParser()
    processor = ObservationProcessor(csv_path)
    storage = ObservationHDF5Storage(h5_path)

    parsed: list[dict[str, str]] = []

    if dates:
        for date in dates:
            for _, link in storage.iter_links(date):
                raw = parser.parse(link)
                parsed.append(processor.process(raw))
        return parsed

    for _, link in storage.iter_links():
        raw = parser.parse(link)
        parsed.append(processor.process(raw))

    return parsed
