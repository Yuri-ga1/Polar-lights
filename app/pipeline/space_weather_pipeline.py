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
    base_out_dir: str = "files",
) -> SpaceWeatherData:
    """
    Скачивает и загружает данные для дальнейшего построения графиков.
    Возвращает DataFrame'ы и пути к файлам (если скачивание прошло успешно).
    """
    paths = SpaceWeatherPaths.from_base(base_out_dir)
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
