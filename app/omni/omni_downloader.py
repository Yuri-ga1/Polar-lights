from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Tuple

import requests


class OmniDownloader:
    """Класс для загрузки данных OMNI (1‑минутное разрешение)."""

    BASE_URL: str = "https://omniweb.gsfc.nasa.gov/cgi/nx1.cgi"
    OMNI_1MIN_VARS = {
        "bx_gse": 14,           # nT
        "by_gse": 15,           # nT
        "bz_gse": 16,           # nT
        "speed": 21,            # km/s
        "flow_pressure": 27,    # nPa
        "ae": 37,               # nT
        "symh": 41              # nT
    }

    DEFAULT_VAR_IDS = tuple(OMNI_1MIN_VARS.values())

    def __init__(self, out_dir: str = ".") -> None:
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)

    def _build_query(self, date: datetime, var_ids: Iterable[int]) -> List[Tuple[str, str]]:
        start_date = date.strftime("%Y%m%d00")
        end_date = (date + timedelta(days=1)).strftime("%Y%m%d00")
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

    def download(self, date_str: str, filename: Optional[str] = None,
                 var_ids: Optional[Iterable[int]] = None) -> str:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        ids = tuple(var_ids) if var_ids is not None else self.DEFAULT_VAR_IDS
        query_params = self._build_query(date, ids)
        try:
            response = requests.get(self.BASE_URL, params=query_params, timeout=60)
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Ошибка при запросе OMNIWeb: {exc}") from exc

        text = response.text
        match = re.search(r"https?://[^\s'\"]+\.lst", text)
        if match:
            try:
                data_text = self._download_lst(match.group(0))
            except Exception:
                data_text = text
        else:
            data_text = text

        if not data_text or not data_text.strip():
            raise RuntimeError(
                "OMNIWeb вернул пустой ответ или формат неизвестен. Проверьте параметры."
            )
        if filename is None:
            filename = f"omni_{date.strftime('%Y%m%d')}.txt"
        file_path = os.path.join(self.out_dir, filename)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(data_text)
        return file_path
