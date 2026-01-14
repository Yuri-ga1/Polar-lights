from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict

import pandas as pd


class KyotoProcessor:
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
        self.folder_path = folder_path

    @staticmethod
    def _parse_date(s: str) -> date:
        return datetime.strptime(s, "%Y-%m-%d").date()

    def _month_file_for_date(self, d: date) -> str:
        yyyymm = f"{d.year:04d}{d.month:02d}"
        return self.MONTH_FILE_PATTERN.format(yyyymm=yyyymm)

    def _full_path(self, filename: str) -> str:
        return os.path.join(self.folder_path, filename)

    @staticmethod
    def _yy_to_year(yy: int) -> int:
        return 1900 + yy if yy >= 80 else 2000 + yy

    def _parse_line(self, line: str) -> Optional[List[Dict]]:
        line = line.strip()
        if not line:
            return None

        m = self.LINE_RE.match(line)
        if not m:
            return None

        yy = int(m.group("yy"))
        mm = int(m.group("mm"))
        dd = int(m.group("dd"))
        year = self._yy_to_year(yy)

        # Берём токен и "хвост" строки после него (важно: numbers могут быть слеплены, типа -99-116)
        parts = line.split()
        if not parts:
            return None
        token = parts[0]
        rest = line[len(token):]

        # Достаём все целые числа из хвоста (работает даже на "-99-116")
        vals = [int(x) for x in re.findall(r"[+-]?\d+", rest)]

        # Ожидаем 24 или 25 значений (иногда первый "0" служебный)
        if len(vals) == 25:
            hourly = vals[-24:]
        elif len(vals) == 24:
            hourly = vals
        else:
            # если больше 24 — берём последние 24; если меньше — строку пропускаем
            if len(vals) > 24:
                hourly = vals[-24:]
            else:
                return None

        base_day = date(year, mm, dd)
        rows: List[Dict] = []
        for hour, dst in enumerate(hourly):
            rows.append(
                {
                    "DateTime": datetime(base_day.year, base_day.month, base_day.day, hour, 0, 0),
                    "date": base_day,
                    "hour": hour,
                    "dst": dst,
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

        df["DateTime"] = pd.to_datetime(df["DateTime"])
        df = df.sort_values("DateTime").reset_index(drop=True)
        return df

    def load(self, date_str: str) -> Optional[pd.DataFrame]:
        d = self._parse_date(date_str)
        filename = self._month_file_for_date(d)
        path = self._full_path(filename)

        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return None

        try:
            df = self._load_month_file(path)
            if df.empty:
                return None

            # надёжная фильтрация по календарному дню
            df = df[df["DateTime"].dt.date == d].reset_index(drop=True)
            return None if df.empty else df
        except Exception:
            return None
