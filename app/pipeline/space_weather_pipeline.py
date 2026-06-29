from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app.gfz.gfz_downloader import GfzDownloader
from app.gfz.gfz_processor import GfzProcessor
from app.kyoto.kyoto_dst_downloader import KyotoDstDownloader
from app.kyoto.kyoto_dst_processor import KyotoProcessor
from app.omni.omni_downloader import OmniDownloader
from app.omni.omni_processor import OmniProcessor
from app.pipeline.datetime_range import (
    concat_dataframes,
    filter_dataframe_by_datetime_range,
    iter_month_anchor_dates,
    validate_datetime_range,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpaceWeatherPaths:
    base_dir: str
    omni_dir: str
    kp_dir: str
    kyoto_dir: str

    @classmethod
    def from_base(cls, base_dir: str) -> "SpaceWeatherPaths":
        return cls(
            base_dir=base_dir,
            omni_dir=os.path.join(base_dir, "omni"),
            kp_dir=os.path.join(base_dir, "kp"),
            kyoto_dir=os.path.join(base_dir, "kyoto"),
        )


@dataclass
class SpaceWeatherData:
    omni: Optional[pd.DataFrame]
    kp: Optional[pd.DataFrame]
    dst: Optional[pd.DataFrame]
    omni_path: Optional[str]
    kp_path: Optional[str]
    dst_path: Optional[str]


def _ensure_output_dirs(paths: SpaceWeatherPaths) -> None:
    os.makedirs(paths.omni_dir, exist_ok=True)
    os.makedirs(paths.kp_dir, exist_ok=True)
    os.makedirs(paths.kyoto_dir, exist_ok=True)


def _safe_download(label: str, download_func) -> Optional[str]:
    try:
        return download_func()
    except Exception as exc:
        logger.warning("Не удалось скачать данные %s: %s", label, exc)
        return None


def prepare_space_weather_data(
    date_str: str,
    download_dir: str = "files",
) -> SpaceWeatherData:
    """
    Скачивает и загружает данные для дальнейшего построения графиков.
    Возвращает DataFrame'ы и пути к файлам (если скачивание прошло успешно).
    """
    paths = SpaceWeatherPaths.from_base(download_dir)
    _ensure_output_dirs(paths)

    omni_path = _safe_download(
        "OMNI",
        lambda: OmniDownloader(out_dir=paths.omni_dir).download(date_str),
    )

    kp_path = _safe_download(
        "GFZ (Kp)",
        lambda: GfzDownloader(out_dir=paths.kp_dir).download(date_str=date_str, fmt="kp2"),
    )

    dst_path = _safe_download(
        "Kyoto Dst",
        lambda: KyotoDstDownloader(out_dir=paths.kyoto_dir).download(date_str),
    )

    omni_df = OmniProcessor(folder_path=paths.omni_dir).load(date_str)

    kp_df = GfzProcessor(folder_path=paths.kp_dir).load(date_str=date_str)

    dst_df = KyotoProcessor(folder_path=paths.kyoto_dir).load(date_str)

    return SpaceWeatherData(
        omni=omni_df,
        kp=kp_df,
        dst=dst_df,
        omni_path=omni_path,
        kp_path=kp_path,
        dst_path=dst_path,
    )


def prepare_space_weather_data_range(
    start_datetime: str,
    end_datetime: str,
    download_dir: str = "files",
) -> SpaceWeatherData:
    start_dt, end_dt = validate_datetime_range(start_datetime, end_datetime)
    paths = SpaceWeatherPaths.from_base(download_dir)
    _ensure_output_dirs(paths)

    month_dates = iter_month_anchor_dates(start_dt, end_dt)

    omni_paths: list[str] = []
    for date_str in month_dates:
        path = _safe_download(
            "OMNI",
            lambda d=date_str: OmniDownloader(out_dir=paths.omni_dir).download(d),
        )
        if path:
            omni_paths.append(path)

    kp_path = _safe_download(
        "GFZ (Kp)",
        lambda: GfzDownloader(out_dir=paths.kp_dir).download(
            start_date=start_dt.date().isoformat(),
            end_date=end_dt.date().isoformat(),
            fmt="kp2",
        ),
    )

    dst_paths: list[str] = []
    for date_str in month_dates:
        path = _safe_download(
            "Kyoto Dst",
            lambda d=date_str: KyotoDstDownloader(out_dir=paths.kyoto_dir).download(d),
        )
        if path:
            dst_paths.append(path)

    omni_df = concat_dataframes(
        OmniProcessor(folder_path=paths.omni_dir).load(date_str)
        for date_str in month_dates
    )
    kp_processor = GfzProcessor(folder_path=paths.kp_dir)
    kp_df = kp_processor.load(
        start_date=start_dt.date().isoformat(),
        end_date=end_dt.date().isoformat(),
    )
    if kp_df is None:
        kp_df = concat_dataframes(
            kp_processor.load(date_str=date_str)
            for date_str in month_dates
        )
    dst_df = concat_dataframes(
        KyotoProcessor(folder_path=paths.kyoto_dir).load(date_str)
        for date_str in month_dates
    )

    omni_df = filter_dataframe_by_datetime_range(omni_df, start_dt, end_dt)
    kp_df = filter_dataframe_by_datetime_range(kp_df, start_dt, end_dt)
    dst_df = filter_dataframe_by_datetime_range(dst_df, start_dt, end_dt)

    return SpaceWeatherData(
        omni=omni_df,
        kp=kp_df,
        dst=dst_df,
        omni_path=";".join(omni_paths) or None,
        kp_path=kp_path,
        dst_path=";".join(dst_paths) or None,
    )
