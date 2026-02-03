from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Tuple

import requests

from app.base_downloader import BaseDownloader

class OmniDownloader(BaseDownloader):
    """Класс для загрузки данных OMNI (1‑минутное разрешение)."""

    BASE_URL: str = "https://omniweb.gsfc.nasa.gov/cgi/nx1.cgi"
    OMNI_1MIN_VARS = {
        "bx_gse": 14,           # nT
        "by_gse": 15,           # nT
        "bz_gse": 16,           # nT
        "speed": 21,            # km/s
        "proton_density": 25,   # n/cc
        "flow_pressure": 27,    # nPa
        "ae": 37,               # nT
        "symh": 41              # nT
    }

    DEFAULT_VAR_IDS = tuple(OMNI_1MIN_VARS.values())

    def __init__(self, out_dir: str = ".") -> None:
        super().__init__(out_dir=out_dir)

    def _build_query(self, start_dt: datetime, end_dt: datetime,
                     var_ids: Iterable[int]) -> List[Tuple[str, str]]:
        start_date = start_dt.strftime("%Y%m%d00")
        end_date = end_dt.strftime("%Y%m%d23")
        print(start_date)
        print(end_date)
        params: List[Tuple[str, str]] = [
            ("activity", "retrieve"),
            ("res", "min"),
            ("spacecraft", "omni_min"),
            ("start_date", start_date),
            ("end_date", end_date),
            ("scale", "Linear"),
            ("view", "0"),
        ]
        for vid in var_ids:
            params.append(("vars", str(vid)))
        return params

    def _download_lst(self, url: str) -> str:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.text
    
    def _retrieve_text(self, params: List[Tuple[str, str]]) -> str:
        try:
            response = requests.get(self.BASE_URL, params=params, timeout=60)
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Ошибка при запросе OMNIWeb: {exc}") from exc

        text = response.text
        match = re.search(r"https?://[^\s'\"]+\.lst", text)
        if match:
            try:
                return self._download_lst(match.group(0))
            except Exception:
                return text
        return text

    def download(self, date_str: str, filename: Optional[str] = None) -> str:
        d = datetime.strptime(date_str, "%Y-%m-%d")

        month_start = d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # первый день следующего месяца
        if d.month == 12:
            next_month_start = d.replace(year=d.year + 1, month=1, day=1,
                                         hour=0, minute=0, second=0, microsecond=0)
        else:
            next_month_start = d.replace(month=d.month + 1, day=1,
                                         hour=0, minute=0, second=0, microsecond=0)

        month_end = (next_month_start - timedelta(days=1)).replace(hour=23)

        params = self._build_query(month_start, month_end, self.DEFAULT_VAR_IDS)
        data_text = self._retrieve_text(params)

        if not data_text or not data_text.strip():
            raise RuntimeError("OMNIWeb вернул пустой ответ или формат неизвестен.")

        if filename is None:
            filename = f"omni_{month_start.strftime('%Y%m')}.txt"

        return self._write_text_file(filename, data_text)
