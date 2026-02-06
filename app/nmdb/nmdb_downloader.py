from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Tuple, Union

import requests

from app.base_classes.base_downloader import BaseDownloader


class NmdbDownloader(BaseDownloader):
    """Загрузчик данных космических лучей из NMDB.

    Этот класс предоставляет метод :meth:`download` для загрузки
    временных рядов счётчиков нейтронных мониторов из базы данных NMDB.
    Пользователь задаёт начальный и конечный момент времени, список
    кодов станций (или ``None`` для выбора всех доступных станций), а
    также дополнительные параметры запроса (таблица данных, тип данных
    и шаг усреднения).  Результат сохраняется в текстовый файл.
    """

    #: URL конечной точки API NMDB, предоставляющей как графики, так и ASCII‐данные
    BASE_URL: str = "https://www.nmdb.eu/nest/draw_graph.php"

    def __init__(self, out_dir: str = ".") -> None:
        super().__init__(out_dir=out_dir)

    @staticmethod
    def _parse_datetime(dt: Union[str, datetime]) -> datetime:
        """Convert a string or datetime to a :class:`datetime` instance.

        Accepts strings in ``YYYY-MM-DD`` or ``YYYY-MM-DD HH:MM`` format.  If
        the time component is omitted it defaults to ``00:00``.

        :param dt: A datetime object or a string representation.
        :return: Parsed datetime in UTC.
        :raises ValueError: If the string is not in a recognised format.
        """
        if isinstance(dt, datetime):
            return dt
        if not isinstance(dt, str):
            raise TypeError(f"Дата должна быть строкой или datetime, получено: {type(dt)!r}")
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(dt, fmt)
                if fmt == "%Y-%m-%d":
                    return parsed.replace(hour=0, minute=0)
                return parsed
            except ValueError:
                continue
        raise ValueError(
            f"Неверный формат даты: {dt!r}. Ожидается 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM'."
        )

    def download(
        self,
        start: Union[str, datetime],
        end: Union[str, datetime],
        stations: Optional[Sequence[str]] = None,
        tabchoice: str = "ori",
        dtype: str = "corr_for_efficiency",
        tresolution: int = 0,
        yunits: int = 0,
        filename: Optional[str] = None,
    ) -> str:
        """Скачать данные NMDB за указанный интервал.

        :param start: Начало интервала (строка 'YYYY-MM-DD' или 'YYYY-MM-DD HH:MM' либо
            объект :class:`datetime.datetime`).
        :param end: Конец интервала (строка или datetime), формат аналогичен ``start``.
        :param stations: Список кодов станций (например, ``["KIEL", "KERG"]``).
            Если ``None`` или пустой список, будут выбраны все станции. В
            соответствии с документацией NMDB для выбора всех станций
            отправляется параметр ``allstations=1``【142008754827029†L59-L61】.
        :param tabchoice: Таблица данных: ``"revori"`` для пересмотренных
            (revised) данных, ``"ori"`` для оригинальных (original) данных или
            ``"1h"`` для проверенных часовых данных.
        :param dtype: Тип данных, один из ``"corr_for_efficiency"``,
            ``"corr_for_pressure"``, ``"uncorrected"`` или ``"pressure_mbar"``
           【142008754827029†L132-L161】.
        :param tresolution: Шаг усреднения в минутах. Значение 0 соответствует
            наилучшему разрешению, в соответствии с параметром ``tresolution``
            из справочной страницы NMDB【142008754827029†L139-L140】.
        :param yunits: Единицы измерения: 0 — абсолютные счёты (counts), 1 —
            процент относительно среднего (для одиночной станции).
        :param filename: Пользовательское имя файла. Если ``None``, имя
            генерируется автоматически.
        :return: Путь к сохранённому файлу.
        :raises RuntimeError: При ошибке запроса или пустом ответе.
        """
        start_dt = self._parse_datetime(start)
        end_dt = self._parse_datetime(end)

        if end_dt < start_dt:
            raise ValueError("Конечная дата не может быть раньше начальной даты.")

        # Формируем параметры запроса в соответствии с API NMDB
        params: dict[str, Union[str, int, List[str]]] = {
            "formchk": 1,
            "tabchoice": tabchoice,
            "dtype": dtype,
            "date_choice": "bydate",
            # дата начала
            "start_year": start_dt.year,
            "start_month": f"{start_dt.month:02d}",
            "start_day": f"{start_dt.day:02d}",
            "start_hour": f"{start_dt.hour:02d}",
            "start_min": f"{start_dt.minute:02d}",
            # дата окончания
            "end_year": end_dt.year,
            "end_month": f"{end_dt.month:02d}",
            "end_day": f"{end_dt.day:02d}",
            "end_hour": f"{end_dt.hour:02d}",
            "end_min": f"{end_dt.minute:02d}",
            "output": "ascii",
            "yunits": yunits,
        }
        # Добавляем параметр усреднения только если не ноль
        if tresolution:
            params["tresolution"] = tresolution

        if stations and len(stations) > 0:
            # Множественный параметр stations[] — requests сам повторит ключ
            params["stations[]"] = list(stations)
        else:
            params["allstations"] = 1

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=120)
            response.raise_for_status()
        except Exception as exc:
            raise RuntimeError(f"Ошибка при запросе NMDB: {exc}") from exc

        text: str = response.text
        if not text or not text.strip():
            raise RuntimeError("NMDB вернул пустой ответ.")

        if filename is None:
            # генерируем имя на основе станций и дат
            if not stations or len(stations) == 0:
                station_part = "all"
            else:
                station_part = "_".join(stations)
            filename = (
                f"nmdb_{station_part}_"
                f"{start_dt.strftime('%Y%m%d%H%M')}-"
                f"{end_dt.strftime('%Y%m%d%H%M')}.txt"
            )

        return self._write_text_file(filename, text)
