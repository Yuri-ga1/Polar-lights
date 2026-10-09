from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

from app.gfz.gfz_downloader import GfzDownloader
from app.gfz.gfz_processor import GfzProcessor
from app.kyoto.kyoto_dst_downloader import KyotoDstDownloader
from app.kyoto.kyoto_dst_processor import KyotoProcessor
from app.omni.omni_downloader import OmniDownloader
from app.omni.omni_processor import OmniProcessor
from app.pipeline.datetime_range import validate_datetime_range
from app.storage.data_paths import DataPaths

from app.logging_config import logged_stage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpaceWeatherPaths:
    """Compatibility view of the canonical raw/processed layout."""

    base_dir: str
    omni_dir: str
    kp_dir: str
    kyoto_dir: str
    omni_processed: Path
    kp_processed: Path
    kyoto_processed: Path

    @classmethod
    def from_base(cls, base_dir: str) -> "SpaceWeatherPaths":
        paths = DataPaths.from_root(base_dir)
        return cls(
            base_dir=str(paths.root),
            omni_dir=str(paths.raw_source("omni")),
            kp_dir=str(paths.raw_source("kp")),
            kyoto_dir=str(paths.raw_source("kyoto")),
            omni_processed=paths.processed_file("omni"),
            kp_processed=paths.processed_file("kp"),
            kyoto_processed=paths.processed_file("kyoto"),
        )


@dataclass
class SpaceWeatherData:
    omni: pd.DataFrame | None
    kp: pd.DataFrame | None
    dst: pd.DataFrame | None
    omni_path: str | None
    kp_path: str | None
    dst_path: str | None


def _safe_download(label: str, action: Callable[[], str]) -> str | None:
    try:
        return action()
    except Exception as exc:
        logger.warning("Download failed for %s: %s", label, exc)
        return None


def _omni_raw_frame(processor: OmniProcessor, raw_path: str) -> pd.DataFrame | None:
    try:
        raw = Path(raw_path).read_text(encoding="utf-8", errors="ignore")
        pre = processor._extract_pre_block(raw)
        frame = processor._parse_table(pre, processor._parse_selected_parameters(pre))
        return None if frame.empty else frame.rename(columns={"DateTime": "datetime"})
    except Exception as exc:
        logger.warning("Failed to process OMNI raw file %s: %s", raw_path, exc)
        return None


def _retrieve_omni(paths: SpaceWeatherPaths, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    processor = OmniProcessor(paths.omni_dir)
    frames: list[pd.DataFrame] = []
    for anchor in pd.date_range(start.normalize(), end.normalize(), freq="MS"):
        raw_path = _safe_download("OMNI", lambda day=anchor: OmniDownloader(paths.omni_dir).download(day.date().isoformat()))
        if raw_path:
            frame = _omni_raw_frame(processor, raw_path)
            if frame is not None:
                frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else None


def _retrieve_kp(paths: SpaceWeatherPaths, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    raw_path = _safe_download("GFZ (Kp)", lambda: GfzDownloader(paths.kp_dir).download(start_date=start.date().isoformat(), end_date=end.date().isoformat(), fmt="kp2"))
    if not raw_path:
        return None
    try:
        return GfzProcessor.to_processed_frame(GfzProcessor._load_kp_file(raw_path))
    except Exception as exc:
        logger.warning("Failed to process GFZ raw file %s: %s", raw_path, exc)
        return None


def _retrieve_dst(paths: SpaceWeatherPaths, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame | None:
    frames: list[pd.DataFrame] = []
    for anchor in pd.date_range(start.normalize(), end.normalize(), freq="MS"):
        raw_path = _safe_download("Kyoto Dst", lambda day=anchor: KyotoDstDownloader(paths.kyoto_dir).download(day.date().isoformat()))
        if raw_path:
            try:
                frame = KyotoProcessor(paths.kyoto_dir)._load_month_file(raw_path)
                if not frame.empty:
                    frames.append(frame)
            except Exception as exc:
                logger.warning("Failed to process Kyoto raw file %s: %s", raw_path, exc)
    return pd.concat(frames, ignore_index=True) if frames else None


def _load_processed_first(paths: SpaceWeatherPaths, start: pd.Timestamp, end: pd.Timestamp) -> SpaceWeatherData:
    omni_processor = OmniProcessor(paths.omni_dir)
    omni_processor.expected_frequency = timedelta(minutes=1)
    kp_processor = GfzProcessor(paths.kp_dir)
    kp_processor.expected_frequency = timedelta(hours=3)
    dst_processor = KyotoProcessor(paths.kyoto_dir)
    dst_processor.expected_frequency = timedelta(hours=1)

    omni = omni_processor.get_data(paths.omni_processed, start, end, lambda ranges: _retrieve_omni(paths, ranges[0][0], ranges[-1][1]))
    kp = kp_processor.get_data(paths.kp_processed, start, end, lambda ranges: _retrieve_kp(paths, ranges[0][0], ranges[-1][1]))
    dst = dst_processor.get_data(paths.kyoto_processed, start, end, lambda ranges: _retrieve_dst(paths, ranges[0][0], ranges[-1][1]))
    return SpaceWeatherData(
        omni=None if omni.empty else omni_processor.with_datetime(omni),
        kp=None if kp.empty else kp_processor.with_datetime(kp),
        dst=None if dst.empty else dst_processor.with_datetime(dst),
        omni_path=str(paths.omni_processed) if paths.omni_processed.exists() else None,
        kp_path=str(paths.kp_processed) if paths.kp_processed.exists() else None,
        dst_path=str(paths.kyoto_processed) if paths.kyoto_processed.exists() else None,
    )


@logged_stage("processing", entry=True)
def prepare_space_weather_data(date_str: str, download_dir: str = "files") -> SpaceWeatherData:
    day = pd.Timestamp(date_str)
    return _load_processed_first(SpaceWeatherPaths.from_base(download_dir), day.normalize(), day.normalize() + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))


@logged_stage("processing", entry=True)
def prepare_space_weather_data_range(start_datetime: str, end_datetime: str, download_dir: str = "files") -> SpaceWeatherData:
    start, end = validate_datetime_range(start_datetime, end_datetime)
    return _load_processed_first(SpaceWeatherPaths.from_base(download_dir), pd.Timestamp(start), pd.Timestamp(end))
