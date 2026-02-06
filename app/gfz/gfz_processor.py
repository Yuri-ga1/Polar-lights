from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd
from app.base_classes.base_processor import BaseProcessor


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date


class GfzProcessor(BaseProcessor):
    """
    Локальный процессор GFZ-файлов (Kp/ap), сохранённых GfzDownloader.

    Правила выбора файла (аналогично GfzDownloader):
    - если задана 1 дата (date_str) -> берём ВЕСЬ месяц и имя:
        gfz_kp_YYYYMM_{fmt}.txt
    - если задан диапазон (start_date + end_date) -> имя:
        gfz_kp_YYYYMMDD-YYYYMMDD_{fmt}.txt

    Возвращает:
    - pd.DataFrame, если файл найден и успешно прочитан
    - None, если файла нет / он пустой / не удалось распарсить
    """

    def __init__(self, folder_path: str) -> None:
        super().__init__(folder_path)

    # ---------- helpers ----------

    @staticmethod
    def _month_range(d: date) -> DateRange:
        last_day = calendar.monthrange(d.year, d.month)[1]
        return DateRange(start=date(d.year, d.month, 1), end=date(d.year, d.month, last_day))

    def _build_filename(
        self,
        *,
        date_str: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str]
    ) -> str:
        if date_str and (start_date or end_date):
            raise ValueError("Передай либо date_str, либо start_date+end_date, но не вместе.")

        if date_str:
            d = self._parse_date(date_str)
            dr = self._month_range(d)
            return f"gfz_kp_{dr.start.strftime('%Y%m')}.txt"

        if not (start_date and end_date):
            raise ValueError("Нужно передать либо date_str, либо оба start_date и end_date.")

        d1 = self._parse_date(start_date)
        d2 = self._parse_date(end_date)
        if d2 < d1:
            raise ValueError("end_date не может быть раньше start_date.")

        return f"gfz_kp_{d1.strftime('%Y%m%d')}-{d2.strftime('%Y%m%d')}.txt"

    # ---------- parsing ----------

    @staticmethod
    def _load_kp_file(filepath: str) -> pd.DataFrame:
        """
        Парсинг kp (или совместимого) формата в DataFrame.
        """
        cols = [
            "year", "month", "day",
            "time1", "time2",
            "col_a", "col_b",
            "kp", "ap",
            "flag",
        ]

        df = pd.read_csv(
            filepath,
            sep=r"\s+",
            names=cols,
            header=None,
            engine="python",
            on_bad_lines="skip",
            dtype={
                "year": int, "month": int, "day": int,
                "time1": float, "time2": float,
                "col_a": float, "col_b": float,
                "kp": float,
                "ap": int,
                "flag": int,
            },
        )

        if df.empty:
            return df

        df["hour"] = df["time1"].astype(float).astype(int)
        df["minute"] = ((df["time1"] - df["hour"]) * 60).round().astype(int)

        df["datetime"] = pd.to_datetime(
            dict(
                year=df["year"],
                month=df["month"],
                day=df["day"],
                hour=df["hour"],
                minute=df["minute"],
            ),
            errors="coerce",
        )

        df = df.drop(columns=["hour", "minute"])

        df = df.dropna(subset=["datetime"]).reset_index(drop=True)
        return df

    # ---------- public API ----------

    def load(
        self,
        date_str: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """
        Загружает (из папки) и парсит файл GFZ по дате или диапазону.

        :return: DataFrame или None
        """
        filename = self._build_filename(
            date_str=date_str,
            start_date=start_date,
            end_date=end_date
        )
        path = self._full_path(filename)

        if not self._is_non_empty_file(path):
            return None

        try:
            df = self._load_kp_file(path)
            if df.empty:
                return None
            return df
        except Exception:
            return None
