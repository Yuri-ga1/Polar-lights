from __future__ import annotations

import os
import calendar
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import requests


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date


class GfzDownloader:
    """
    Загрузчик индекса Kp с GFZ по endpoint:
    https://kp.gfz.de/kpdata?startdate=YYYY-MM-DD&enddate=YYYY-MM-DD&format=kp2

    Правила:
    - download(date_str="YYYY-MM-DD") -> скачивает ВЕСЬ месяц этой даты
    - download(start_date="YYYY-MM-DD", end_date="YYYY-MM-DD") -> скачивает диапазон как есть
    """

    BASE_URL: str = "https://kp.gfz.de/kpdata"

    def __init__(self, out_dir: str = ".") -> None:
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)

    @staticmethod
    def _parse_date(s: str) -> date:
        return datetime.strptime(s, "%Y-%m-%d").date()

    @staticmethod
    def _month_range(d: date) -> DateRange:
        last_day = calendar.monthrange(d.year, d.month)[1]
        return DateRange(start=date(d.year, d.month, 1), end=date(d.year, d.month, last_day))

    def _request_kp(self, dr: DateRange, fmt: str) -> str:
        params = {
            "startdate": dr.start.isoformat(),
            "enddate": dr.end.isoformat(),
            "format": fmt,
        }
        resp = requests.get(self.BASE_URL, params=params, timeout=60)
        resp.raise_for_status()
        text = resp.text
        if not text.strip():
            raise RuntimeError("GFZ вернул пустой ответ.")
        return text

    def download(
        self,
        date_str: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        fmt: str = "kp2",
        filename: Optional[str] = None,
    ) -> str:
        """
        Скачивает данные Kp.

        Варианты вызова:
        - download(date_str="2025-11-01") -> весь ноябрь 2025
        - download(start_date="2025-11-01", end_date="2025-11-12") -> ровно диапазон

        :param date_str: одна дата (YYYY-MM-DD) для режима "весь месяц"
        :param start_date: дата начала диапазона (YYYY-MM-DD)
        :param end_date: дата конца диапазона (YYYY-MM-DD)
        :param fmt: параметр format (по умолчанию kp2)
        :param filename: имя файла; если None — генерируется автоматически
        :return: путь к сохранённому файлу
        """
        if date_str and (start_date or end_date):
            raise ValueError("Передай либо date_str, либо start_date+end_date, но не вместе.")

        if date_str:
            d = self._parse_date(date_str)
            dr = self._month_range(d)
            default_name = f"gfz_kp_{dr.start.strftime('%Y%m')}.txt"
        else:
            if not (start_date and end_date):
                raise ValueError("Нужно передать либо date_str, либо оба start_date и end_date.")
            
            d1 = self._parse_date(start_date)
            d2 = self._parse_date(end_date)

            if d2 < d1:
                raise ValueError("end_date не может быть раньше start_date.")
            
            dr = DateRange(start=d1, end=d2)
            default_name = f"gfz_kp_{dr.start.strftime('%Y%m%d')}-{dr.end.strftime('%Y%m%d')}.txt"

        # --- Запрос ---
        data_text = self._request_kp(dr, fmt)

        # --- Сохранение ---
        save_name = filename or default_name
        file_path = os.path.join(self.out_dir, save_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(data_text)

        return file_path
