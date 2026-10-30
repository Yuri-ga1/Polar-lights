from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional, List, Dict

import pandas as pd
from app.base_classes.base_processor import BaseProcessor

from app.logging_config import logged_stage
from app.storage.raw_retention import raw_locked


class KyotoProcessor(BaseProcessor):
    """
    Локальный процессор файлов Dst (Kyoto), сохранённых KyotoDstDownloader.

    Поддерживается ТОЛЬКО загрузка по одной дате:
        load(date_str="YYYY-MM-DD")

    Ожидаемое имя файла:
        dst_YYYYMM.for

    Возвращает:
    - pd.DataFrame (24 строки: hour=0..23) или None
    """

    MONTH_FILE_PATTERN = "dst_{yyyymm}.for"
    LINE_RE = re.compile(r"^DST(?P<yy>\d{2})(?P<mm>\d{2})\*(?P<dd>\d{2})")

    def __init__(self, folder_path: str) -> None:
        super().__init__(folder_path)

    def _month_file_for_date(self, d: date) -> str:
        yyyymm = f"{d.year:04d}{d.month:02d}"
        return self.MONTH_FILE_PATTERN.format(yyyymm=yyyymm)

    @staticmethod
    def _parse_line(line: str) -> Optional[List[Dict]]:
        line = line.rstrip("\r\n")
        m = KyotoProcessor.LINE_RE.match(line)
        if not m:
            return None
        if len(line) < 120:
            return None

        # Kyoto uses fixed-width records: base at 17–20, hourly values at
        # 21–116, daily mean at 117–120. Splitting shifts hours or joins values.
        try:
            century = int(line[14:16]) if line[14:16].strip() else 19
            year = century * 100 + int(m.group("yy"))
            base_day = date(year, int(m.group("mm")), int(m.group("dd")))
            base = int(line[16:20]) * 100
            hourly = [int(line[offset:offset + 4]) for offset in range(20, 116, 4)]
        except ValueError:
            return None

        rows: List[Dict] = []
        for hour, dst in enumerate(hourly):
            rows.append(
                {
                    "datetime": datetime(base_day.year, base_day.month, base_day.day, hour, 0, 0),
                    "dst": float("nan") if dst == 9999 else base + dst,
                }
            )
        return rows

    def _load_month_file(self, path: str) -> pd.DataFrame:
        rows: List[Dict] = []
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                parsed = self._parse_line(line)
                if parsed:
                    rows.extend(parsed)

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        return df

    @logged_stage("processing", entry=False)
    @raw_locked
    def load(self, date_str: str) -> Optional[pd.DataFrame]:
        d = self._parse_date(date_str)
        filename = self._month_file_for_date(d)
        path = self._full_path(filename)

        if not self._is_non_empty_file(path):
            return None

        try:
            df = self._load_month_file(path)
            if df.empty:
                return None

            # надёжная фильтрация по календарному дню
            return None if df.empty else df
        except Exception:
            return None
