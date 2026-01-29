from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import requests

from app.simurg.simurg_client import SimurgClient

__all__ = [
    "GimDownloader",
    "RotiDownloader",
    "AdjustedTecDownloader",
    "KeogramDownloader",
]

class _SimurgDownloader:
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
        query_id = self.client.create_or_reuse_query_id(
            start_time=start_iso,
            end_time=end_iso,
            method=self._method,
            args_params=self._args,
        )
        file_path = self._wait_and_download(query_id)
        return file_path

    def _wait_and_download(self, query_id: str) -> str:
        """Ожидает готовность и скачивает результат."""
        while True:
            status_data = self.client.check_status(query_id)
            status = status_data.get("status")

            if status == "done":
                result_path = (status_data.get("paths") or {}).get("data")
                if result_path:
                    full_result_url = (
                        f"{self.client.download_url}/{str(result_path).lstrip('/')}"
                    )
                    return self._download_result(full_result_url)
                raise RuntimeError(
                    f"Запрос {query_id} завершён (done), но paths.data отсутствует: {status_data}"
                )

            if status in {"new", "prepared", "processed", "plot"}:
                time.sleep(self.client.polling_interval)
                continue

            raise RuntimeError(f"Запрос {query_id} имеет неожиданный статус: {status_data}")

    def _download_result(
        self,
        url: str,
        chunk_size: int = 1024 * 1024,
    ) -> str:
        """Скачивает файл с докачкой до полного получения."""
        print(f"Downloading results from {url}")
        filename = os.path.basename(url)
        file_path = os.path.join(self.out_dir, filename)

        def _extract_total_size(resp: requests.Response, offset: int) -> Optional[int]:
            content_range = resp.headers.get("Content-Range")
            if content_range and "/" in content_range:
                total_str = content_range.split("/")[-1]
                if total_str.isdigit():
                    return int(total_str)
            content_length = resp.headers.get("Content-Length")
            if content_length and content_length.isdigit():
                length = int(content_length)
                if resp.status_code == 206:
                    return offset + length
                return length
            return None

        while True:
            offset = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}

            try:
                resp = requests.get(
                    url,
                    timeout=self.client.timeout,
                    verify=self.client.verify,
                    headers=headers,
                    stream=True,
                )
            except requests.RequestException:
                time.sleep(self.client.polling_interval)
                continue

            if resp.status_code not in (200, 206):
                raise RuntimeError(f"Не удалось скачать по result_url {url}: {resp.status_code}")

            if resp.status_code == 200 and offset:
                offset = 0
                mode = "wb"
            else:
                mode = "ab" if offset else "wb"

            total_size = _extract_total_size(resp, offset)
            try:
                with open(file_path, mode) as f:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
            except requests.RequestException:
                time.sleep(self.client.polling_interval)
                continue

            final_size = os.path.getsize(file_path)
            if total_size is None or final_size >= total_size:
                return file_path


class GimDownloader(_SimurgDownloader):
    """Загрузчик для глобальных ионосферных карт (GIM)."""

    _method = "/gimmap"


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



class AdjustedTecDownloader(_SimurgDownloader):
    """Загрузчик для «adjusted TEC» (откалиброванный TEC)."""

    _method = "adjusted_tec"


class KeogramDownloader(_SimurgDownloader):
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
