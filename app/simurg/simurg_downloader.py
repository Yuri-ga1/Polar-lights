from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.simurg.simurg_client import SimurgClient

__all__ = [
    "GimDownloader",
    "RotiDownloader",
    "AdjustedTecDownloader",
    "KeogramDownloader",
]


class _BaseDownloader:
    """Базовый класс-загрузчик для конкретного типа продукта.

    В подклассах следует определить атрибут ``product_type`` и при
    необходимости переопределить ``_make_time_range``.
    """

    _method: str = ""
    _args: Dict[str, Any] = {}

    def __init__(self, client: SimurgClient, out_dir: str = "."):
        self.client = client
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)

    def _to_simurg_date(self, dt: datetime) -> str:
        """Преобразует datetime в ISO 8601 без дробной части секунд."""
        return dt.strftime("%Y-%m-%d %H:%M")

    def _make_time_range(self, date_str: str, end_date: Optional[str] = None) -> tuple[str, str]:
        """Формирует строковые временные границы.

        Если задан только ``date_str``, возвращает интервал в 24 часа
        (от 00:00 до 23:59:59) этого дня.  Если задан диапазон (``end_date``),
        использует начало и конец диапазона.  Даты могут быть в формате
        ``YYYY-MM-DD``.
        """
        start_date = datetime.strptime(date_str, "%Y-%m-%d")
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
        else:
            end_dt = start_date + timedelta(days=1)
        return self._to_simurg_date(start_date), self._to_simurg_date(end_dt)

    def download(self, date_str: str, end_date: Optional[str] = None, **kwargs: Any) -> str:
        """Запускает формирование запроса и скачивает результат.

        :param date_str: начальная дата (формат ``YYYY-MM-DD``)
        :param end_date: опциональная конечная дата (формат ``YYYY-MM-DD``)
        :param kwargs: дополнительные параметры для API
        :returns: путь к результату
        """
        start_iso, end_iso = self._make_time_range(date_str, end_date)
        query_id = self.client.create_query(
            start_time=start_iso,
            end_time=end_iso,
            method=self._method,
            args_params=self._args,
            **kwargs,
        )
        file_path = self.client.wait_and_download(query_id, dest_dir=self.out_dir)
        return file_path


class GimDownloader(_BaseDownloader):
    """Загрузчик для глобальных ионосферных карт (GIM)."""

    _method = "/gimmap"


class RotiDownloader(_BaseDownloader):
    """Загрузчик для карт индекса ROTI."""

    _method = "create_map"
    _args = {
        "coordinates":{
            "minlat": -90,
            "maxlat": 90,
            "minlon": -180,
            "maxlon": 180
        },
        "options": {
            "product_type": "roti",
            "format": "hdf5"
        },
        "flags":{
            "create_plots": False,
            "create_movie": False
        }
    } 



class AdjustedTecDownloader(_BaseDownloader):
    """Загрузчик для «adjusted TEC» (откалиброванный TEC)."""

    _method = "adjusted_tec"


class KeogramDownloader(_BaseDownloader):
    """Загрузчик для кеограмм.

    Кеограмма — это изображение, представляющее временную эволюцию
    горизонтального среза ионосферного параметра по выбранной широте
    или долготе.  В SIMuRG кеограммы могут формироваться по данным
    ROTI, TEC или другим продуктам.  Для создания запроса
    необходимо указать дополнительные параметры, такие как фиксированная
    широта/долгота и тип параметра.  Эти параметры передаются в
    ``download`` через ``kwargs``.
    """

    _method = "keogram"
