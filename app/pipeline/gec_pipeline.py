from __future__ import annotations

import pandas as pd

from app.logging_config import get_logger, logged_stage
from app.pipeline.datetime_range import validate_datetime_range
from app.simurg.gec_downloader import GecDownloader
from app.simurg.gec_processor import GecProcessor
from app.storage.data_paths import DataPaths
from app.storage.raw_retention import raw_operation
from app.storage.timeseries import TimeSeriesStorage, utc

logger = get_logger(__name__)


@logged_stage("processing", entry=True)
def prepare_gec_data_range(
    start_datetime: str,
    end_datetime: str,
    sources: list[str],
    normalization: str = "gec_tec",
    download_dir: str = "files",
    *,
    refresh: bool = False,
    refresh_current_year: bool = True,
    timeout: float = 60,
    cache_only: bool = False,
) -> pd.DataFrame | None:
    """Return datetime plus one column per source, without filling missing GEC.

    Cache complete yearly responses (the smallest API unit). A numeric
    __checked_year column records successful API queries in the same store,
    without inferring cadence or interpreting gaps as unavailable data.
    Archives without this marker are conservatively fetched again. Current-year data is
    refreshed by default; disable refresh_current_year for offline cache reads.
    Normalization is preserved in archive names and DataFrame.attrs.
    cache_only returns None when acquisition or refresh would be required.
    """
    start, end = validate_datetime_range(
        utc(start_datetime).tz_localize(None), utc(end_datetime).tz_localize(None)
    )
    paths = DataPaths.from_root(download_dir)
    raw = paths.raw_source("gec")
    downloader = GecDownloader(raw, sources, normalization, timeout=timeout)
    processor = GecProcessor(raw)
    sources = downloader.sources
    stores = {
        s: TimeSeriesStorage(paths.processed_file(f"gec/{normalization}/{s}"))
        for s in sources
    }
    with raw_operation(raw) as operation:
        frames = {s: store.read() for s, store in stores.items()}
        for year in range(start.year, end.year + 1):
            needed = []
            for source, frame in frames.items():
                checked = (
                    "__checked_year" in frame and frame["__checked_year"].eq(year).any()
                )
                if (
                    not checked
                    or refresh
                    or (
                        refresh_current_year and year == pd.Timestamp.now(tz="UTC").year
                    )
                ):
                    needed.append(source)
            logger.info(
                "GEC processed cache inspected",
                extra={
                    "event": "cache_miss" if needed else "cache_hit",
                    "context": {
                        "year": year,
                        "sources": needed,
                        "normalization": normalization,
                    },
                },
            )
            if not needed:
                continue
            if cache_only:
                return None
            acquisition = GecDownloader(raw, needed, normalization, timeout=timeout)
            path = acquisition.download(year, year, refresh=True)
            rows = processor.load(path, needed)
            if not (rows.index.year == year).all():
                raise ValueError(
                    "SIMuRG returned timestamps outside the requested year"
                )
            for source in needed:
                incoming = rows[[source]].copy()
                incoming.loc[incoming.index[0], "__checked_year"] = year
                frames[source] = stores[source].merge(incoming)
                operation.verify_frame(stores[source].path, incoming)
        result = pd.concat([frames[s].reindex(columns=[s]) for s in sources], axis=1)
        result = result.sort_index().loc[utc(start) : utc(end)].reset_index()
        result.attrs.update(normalization=normalization, sources=sources)
        if normalization == "gec_tec":
            result.attrs["units"] = "TECU"
        return result
