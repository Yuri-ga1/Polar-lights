from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import requests

from app.base_classes.base_downloader import BaseDownloader
from app.logging_config import logged_stage
from app.storage.raw_retention import raw_locked


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
        start_date = start_dt.strftime("%Y%m%d%H")
        end_date = end_dt.strftime("%Y%m%d%H")
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

    @staticmethod
    def _validate_text(text: str) -> None:
        """Reject error pages returned with HTTP 200 before caching them."""
        from app.omni.omni_processor import OmniProcessor

        pre = OmniProcessor._extract_pre_block(text)
        try:
            parameters = OmniProcessor._parse_selected_parameters(pre)
            row = re.search(
                r"^\s*\d{4}\s+\d{1,3}\s+\d{1,2}\s+\d{1,2}\s+(.+)$",
                pre,
                re.MULTILINE,
            )
            if row is None or len(row.group(1).split()) != len(parameters):
                raise ValueError("Не найдены строки данных OMNI.")
            for value in row.group(1).split():
                float(value)
        except ValueError as exc:
            detail = re.sub(r"<[^>]*>", " ", text)
            detail = " ".join(detail.split())[:300]
            raise RuntimeError(
                f"OMNIWeb вернул ответ без таблицы данных: {detail}"
            ) from exc

    def _get_existing_file(self, filename: str, min_size_bytes: int = 1) -> Optional[str]:
        path = super()._get_existing_file(filename, min_size_bytes)
        if path:
            try:
                self._validate_text(Path(path).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, RuntimeError):
                return None
        return path
    
    def _retrieve_text(self, params: List[Tuple[str, str]]) -> str:
        try:
            response = requests.get(self.BASE_URL, params=params, timeout=60)
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Ошибка при запросе OMNIWeb: {exc}") from exc

        text = response.text
        match = re.search(r"https?://[^\s'\"]+\.lst", text)
        if match:
            return self._download_lst(match.group(0))
        return text

    @logged_stage("download", entry=False)
    @raw_locked
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

        if filename is None:
            filename = f"omni_{month_start.strftime('%Y%m')}.txt"

        existing_file = self._get_existing_file(filename)
        if existing_file:
            return existing_file

        params = self._build_query(month_start, month_end, self.DEFAULT_VAR_IDS)
        data_text = self._retrieve_text(params)

        self._validate_text(data_text)

        return self._write_text_file(filename, data_text)

    @logged_stage("download", entry=False)
    @raw_locked
    def download_range(self, start: datetime, end: datetime, columns: Iterable[str] | None = None) -> str:
        """Backend range API; the existing monthly download API is unchanged.

        OMNIWeb accepts hour boundaries. Only requested variables and hours
        intersecting a missing interval are fetched; callers trim the result.
        """
        names = {
            "omni_bx": 14, "omni_by": 15, "omni_bz": 16,
            "omni_speed": 21, "omni_proton_density": 25,
            "omni_flow_pressure": 27, "omni_ae": 37, "omni_sym_h": 41,
        }
        if end < start:
            raise ValueError("end must be greater than or equal to start")
        variables = sorted(
            self.DEFAULT_VAR_IDS if columns is None else {names[column] for column in columns}
        )
        filename = f"omni_{start:%Y%m%d%H}-{end:%Y%m%d%H}_{'-'.join(map(str, variables))}.txt"
        existing = self._get_existing_file(filename)
        if existing:
            return existing
        params = self._build_query(start, end, variables)
        text = self._retrieve_text(params)
        self._validate_text(text)
        return self._write_text_file(filename, text)
