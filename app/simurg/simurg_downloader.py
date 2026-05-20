from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.base_classes.base_downloader import BaseDownloader
from app.simurg.simurg_client import SimurgClient

__all__ = [
    "RotiDownloader",
    "AdjustedTecDownloader",
]

class _SimurgDownloader(BaseDownloader):
    """Базовый класс-загрузчик для конкретного типа продукта.

    В подклассах следует определить атрибут ``product_type`` и при
    необходимости переопределить ``_make_time_range``.
    """

    _method: str = ""
    _args: Dict[str, Any] = {}

    def __init__(self, client: SimurgClient, out_dir: str = "."):
        super().__init__(out_dir=out_dir)
        self.client = client

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
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            end_dt = start_date + timedelta(days=1) - timedelta(minutes=1)
        return self._to_simurg_date(start_date), self._to_simurg_date(end_dt)

    def download(self, date_str: str, end_date: Optional[str] = None) -> str:
        """Запускает формирование запроса и скачивает результат.

        :param date_str: начальная дата (формат ``YYYY-MM-DD``)
        :param end_date: опциональная конечная дата (формат ``YYYY-MM-DD``)
        :param kwargs: дополнительные параметры для API
        :returns: путь к результату
        """
        start_iso, end_iso = self._make_time_range(date_str, end_date)
        query_ids = self.client.create_or_reuse_query_ids(
            start_time=start_iso,
            end_time=end_iso,
            method=self._method,
            args_params=self._args,
        )
        file_path = self._wait_and_download(query_ids)
        return file_path

    def _wait_and_download(self, query_ids: list[str]) -> str:
        """Ожидает готовность по множеству id и скачивает все готовые результаты."""
        pending_ids = {str(query_id) for query_id in query_ids}
        if not pending_ids:
            raise RuntimeError("SIMURG не вернул id запросов для проверки статуса")

        self.client.query_ids.update(pending_ids)
        downloaded_paths: list[str] = []

        while pending_ids:
            status_map = self.client.check_statuses(sorted(pending_ids))
            done_ids: list[str] = []

            for query_id, status_data in status_map.items():
                status = status_data.get("status")
                if self.client.status_has_keyword(status, "done"):
                    result_path = (status_data.get("paths") or {}).get("data")
                    if not result_path:
                        raise RuntimeError(
                            f"Запрос {query_id} завершён (done), но paths.data отсутствует: {status_data}"
                        )

                    full_result_url = f"{self.client.download_url}/{str(result_path).lstrip('/')}"
                    downloaded_paths.append(self._download_result(full_result_url))
                    done_ids.append(query_id)
                    continue

                if status_data == 'not_found':
                    raise RuntimeError(f"Запрос {query_id} был удален или изменен")

                in_progress_keywords = ("new", "prepared", "processed", "plot", "processing")
                if not any(self.client.status_has_keyword(status, keyword) for keyword in in_progress_keywords):
                    raise RuntimeError(f"Запрос {query_id} имеет неожиданный статус: {status_data}")

            if done_ids:
                pending_ids.difference_update(done_ids)
                self.client.remove_query_ids(done_ids)
                continue

            time.sleep(self.client.polling_interval)

        if not downloaded_paths:
            raise RuntimeError("Не удалось скачать данные SIMURG: отсутствуют готовые запросы")

        return downloaded_paths[0]

    def _download_result(self, url: str) -> str:
        return super()._download_result(
            url,
            timeout=self.client.timeout,
            verify=self.client.verify,
            polling_interval=self.client.polling_interval,
        )


class RotiDownloader(_SimurgDownloader):
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

    def _make_time_range(self, date_str: str, end_date: Optional[str] = None) -> tuple[str, str]:
        """Формирует диапазон ``target ± 1 день`` для выгрузки ROTI.

        При передаче одной даты (``YYYY-MM-DD``) на SIMURG отправляется интервал
        от 00:00 предыдущего дня до 00:00 следующего за целевым днём.
        В результате имя файла на стороне SIMURG начинается с DOY предыдущего дня.
        """
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        start_date = target_date - timedelta(days=1)
        end_dt = target_date + timedelta(days=1, hours=23, minutes=59)
        return self._to_simurg_date(start_date), self._to_simurg_date(end_dt)



class AdjustedTecDownloader(_SimurgDownloader):
    """Загрузчик для «adjusted TEC» (откалиброванный TEC)."""

    _method = "create_map"
    _args = {
        "coordinates":{
            "minlat": -90,
            "maxlat": 90,
            "minlon": -180,
            "maxlon": 180
        },
        "options": {
            "product_type": "tec_adjusted",
            "format": "hdf5",
            "subsolar": False,
            "mageq": False,
            "cutoff": 10,
            "timestep": 300

        },
        "flags":{
            "create_plots": False,
            "create_movie": False
        }
    } 
