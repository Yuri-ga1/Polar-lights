from __future__ import annotations

import os
import time
from typing import Any, Dict

import requests


class SimurgClient:
    """Базовый клиент для работы с SIMuRG API.

    Предоставляет методы для создания запроса, проверки его статуса и
    скачивания результата.  Конечные точки API по умолчанию заданы
    значениями, актуальными на момент разработки, но могут быть
    изменены через параметры конструктора.
    
    :param polling_interval: интервал в секундах между опросами
    """

    def __init__(
        self,
        email: str,
        base_url: str = "https://simurg.iszf.irk.ru/api",
        polling_interval: int = 60,
        timeout: int = 30,
        verify: bool = True
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.polling_interval = polling_interval
        self.verify = verify
        self.email = email

    def create_query(
        self,
        start_time: str,
        end_time: str,
        method: str,
        args_params: Dict[str, Any],
    ) -> str:
        """Создаёт запрос к SIMuRG для получения данных.

        :param start_time: строка ISO 8601 (например, "2025-11-12T00:00:00")
        :param end_time:   строка ISO 8601 (конец интервала)
        :param method: тип продукта (``"gim"``, ``"create_map"``, ``"adjusted_tec"``, ``"keogram"``)
        :param args_params: словарь дополнительных параметров для API
        :returns: идентификатор запроса, возвращённый сервером
        :raises RuntimeError: при ошибке HTTP или отсутствия идентификатора
        """
        url = f"{self.base_url}"
        payload: Dict[str, Any] = {"method": method,
                                   "args": {
                                       "email": self.email,
                                       "begin": start_time,
                                       "end": end_time,
                                    }
                                }
        # дополнительные параметры
        payload["args"].update(args_params)

        try:
            resp = requests.post(url, json=payload, timeout=self.timeout, verify=self.verify)
        except Exception as exc:
            raise RuntimeError(f"Ошибка соединения с {url}: {exc}") from exc
        
        if resp.status_code != 200:
            raise RuntimeError(
                f"Сервер вернул код {resp.status_code} при создании запроса. Ответ: {resp.text}. Url: {url}"
            )
        
        data = resp.json()
        query_id = data.get("id") or data.get("query_id")
        if not query_id:
            raise RuntimeError(
                f"Не удалось получить идентификатор запроса из ответа: {data}"
            )
        return str(query_id)

    def check_status(self, query_id: str) -> Dict[str, Any]:
        """Проверяет статус запроса.

        :param query_id: идентификатор запроса
        :returns: JSON-ответ со статусом.  Обычно поле ``status`` содержит
          строку ``pending``, ``running`` или ``done``.  В случае
          завершения может присутствовать ссылка ``result_url`` или
          другая информация о файле.
        :raises RuntimeError: при ошибке соединения или HTTP-статусе != 200
        """
        url = f"{self.base_url}"
        try:
            resp = requests.post(url, timeout=self.timeout, verify=self.verify,
                                 json={
                                     'method': 'check',
                                     'args':{'email': self.email}
                                    })
            queries = resp.json()
            query = next(
                (q for q in queries if q["id"] == query_id),
                None
            )
            if query is None:
                return {
                    "status": "not_found"
                }

        except Exception as exc:
            raise RuntimeError(f"Ошибка запроса статуса {url}: {exc}") from exc
        if resp.status_code != 200:
            raise RuntimeError(
                f"Сервер вернул код {resp.status_code} при запросе статуса. Ответ: {resp.text}"
            )
        return query

    def download_result(self, url: str, dest_dir: str = ".") -> str:
        """Скачивает результат запроса.

        :param url: ссылка для скачивания
        :param dest_dir: директория для сохранения файла
        :returns: путь к сохранённому файлу
        :raises RuntimeError: при ошибке загрузки или отсутствии файла
        """
        r = requests.get(url, timeout=self.timeout, verify=self.verify)

        if r.status_code != 200:
            raise RuntimeError(
                f"Не удалось скачать по result_url {url}: {r.status_code}"
            )
        
        os.makedirs(dest_dir, exist_ok=True)
        filename = os.path.basename(url)
        file_path = os.path.join(dest_dir, filename)

        with open(file_path, "wb") as f:
            f.write(r.content)
        return file_path

    def wait_and_download(
        self,
        query_id: str,
        dest_dir: str = ".",
        max_attempts: int = 40,
    ) -> str:
        """Ожидает завершения запроса и скачивает результат.

        Периодически опрашивает статус запроса.  Если статус
        становится ``done``, скачивает файл и возвращает путь.  В
        случае превышения количества попыток или отказа сервера
        возбуждает исключение.

        :param query_id: идентификатор запроса
        :param dest_dir: директория для сохранения
        :param max_attempts: максимальное число попыток опроса
        :returns: путь к результату
        """
        for attempt in range(max_attempts):
            status_data = self.check_status(query_id)
            status = status_data.get("status")

            if status == "done":
                result_url = status_data['paths']['data']

                if result_url:
                    full_result_url = f'{self.base_url}/{result_url}'
                    return self.download_result(full_result_url, dest_dir)
                
            elif status in {'new', 'prepared', 'processed', 'plot'}:
                time.sleep(self.polling_interval)
            else:
                raise RuntimeError(
                    f"Запрос {query_id} имеет неожиданный статус: {status_data}"
                )
        raise RuntimeError(
            f"Превышено количество попыток ожидания выполнения запроса {query_id}"
        )