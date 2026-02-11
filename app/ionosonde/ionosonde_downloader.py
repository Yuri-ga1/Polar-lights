from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Union

import requests

from app.base_classes.base_downloader import BaseDownloader


@dataclass(frozen=True)
class StationDownloadReport:
    station: str
    start: date
    end: date
    requested_days: int
    downloaded_days: int
    output_path: Optional[str]
    skipped_reason: Optional[str]


class IonosondeDownloader(BaseDownloader):
    BASE_ROOT: str = "https://downloads.sws.bom.gov.au/wdc/wdc_ion_auto"

    def __init__(
        self,
        out_dir: str = ".",
        product: str = "scl",
        dataset: str = "auto",
        timeout: float = 60.0,
    ) -> None:
        super().__init__(out_dir=out_dir)
        self.product = product
        self.dataset = dataset
        self.timeout = timeout

        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }

        # cache: (station, yy) -> set({"250101.scl", ...})
        self._year_listing_cache: Dict[Tuple[str, str], Set[str]] = {}

    # -------------------------
    # date helpers
    # -------------------------

    @staticmethod
    def _parse_date(d: Union[str, date, datetime]) -> date:
        if isinstance(d, date) and not isinstance(d, datetime):
            return d
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, str):
            return datetime.strptime(d, "%Y-%m-%d").date()
        raise TypeError(f"Дата должна быть str/date/datetime, получено: {type(d)!r}")

    @staticmethod
    def _daterange(d0: date, d1: date):
        cur = d0
        while cur <= d1:
            yield cur
            cur += timedelta(days=1)

    @staticmethod
    def _yy(d: date) -> str:
        return f"{d.year % 100:02d}"

    @staticmethod
    def _yymmdd(d: date) -> str:
        return f"{d.year % 100:02d}{d.month:02d}{d.day:02d}"

    # -------------------------
    # http helpers
    # -------------------------

    def _get_text(self, url: str) -> str:
        resp = requests.get(url, headers=self._headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    # -------------------------
    # station discovery
    # -------------------------

    def _list_all_stations(self) -> List[str]:
        url = f"{self.BASE_ROOT}/"
        try:
            html = self._get_text(url)
        except Exception:
            return []

        stations = re.findall(r'href=[\'"]([a-z0-9]{3,12})/[\'"]', html, flags=re.IGNORECASE)
        stations = [s for s in stations if s.lower() not in ("parent", "parentdirectory")]

        seen = set()
        ordered: List[str] = []
        for s in stations:
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        return ordered

    # -------------------------
    # url builder (как было)
    # -------------------------

    def _build_urls_for_date_window(
        self,
        station: str,
        target_date: Union[str, date, datetime],
        days_range: int = 13,
    ) -> List[str]:
        center = self._parse_date(target_date)
        d0 = center - timedelta(days=days_range)
        d1 = center + timedelta(days=days_range)

        urls: List[str] = []
        for d in self._daterange(d0, d1):
            yy = self._yy(d)
            yymmdd = self._yymmdd(d)
            urls.append(
                f"{self.BASE_ROOT}/{station}/{self.product}/{self.dataset}/{yy}/{yymmdd}.{self.product}"
            )
        return urls

    # -------------------------
    # NEW: listing-based availability check (без скачивания данных)
    # -------------------------

    def _year_dir_url(self, station: str, yy: str) -> str:
        return f"{self.BASE_ROOT}/{station}/{self.product}/{self.dataset}/{yy}/"

    def _list_files_in_year_dir(self, station: str, yy: str) -> Set[str]:
        """
        Читает HTML-листинг папки года и возвращает множество имён файлов
        вида {"250101.scl", ...}. Кэшируется в рамках экземпляра.
        """
        key = (station, yy)
        if key in self._year_listing_cache:
            return self._year_listing_cache[key]

        url = self._year_dir_url(station, yy)
        try:
            html = self._get_text(url)
        except Exception:
            files: Set[str] = set()
            self._year_listing_cache[key] = files
            return files

        ext = re.escape(f".{self.product}")
        files = set(re.findall(rf'href=[\'"](\d{{6}}{ext})[\'"]', html, flags=re.IGNORECASE))
        self._year_listing_cache[key] = files
        return files

    def _station_has_min_days(
        self,
        station: str,
        d0: date,
        d1: date,
        min_days_present: int,
    ) -> bool:
        """
        Проверяет наличие как минимум min_days_present дневных файлов в окне [d0..d1]
        у указанной станции, читая только листинги каталогов (без скачивания файлов).
        """
        needed_by_year: Dict[str, List[str]] = {}
        for d in self._daterange(d0, d1):
            yy = self._yy(d)
            fname = f"{self._yymmdd(d)}.{self.product}"
            needed_by_year.setdefault(yy, []).append(fname)

        found = 0
        for yy, needed_files in needed_by_year.items():
            available_files = self._list_files_in_year_dir(station, yy)
            if not available_files:
                continue

            # считаем пересечение
            for f in needed_files:
                if f in available_files:
                    found += 1
                    if found >= min_days_present:
                        return True

        return False

    def _filter_available_stations(
        self,
        stations: List[str],
        d0: date,
        d1: date,
        min_days_present: int,
    ) -> List[str]:
        """
        Возвращает только станции, которые имеют >= min_days_present файлов в окне.
        """
        available: List[str] = []
        for st in stations:
            try:
                if self._station_has_min_days(st, d0, d1, min_days_present=min_days_present):
                    available.append(st)
            except Exception:
                # если где-то сетевой/парсинг косяк — считаем станцию недоступной
                continue
        return available

    # -------------------------
    # public API
    # -------------------------

    def download(
        self,
        target_date: Union[str, date, datetime],
        station: Optional[str] = None,
        days_range: int = 13,
        min_days_present: int = 1,
        filename: Optional[str] = None,
    ) -> StationDownloadReport:
        center = self._parse_date(target_date)
        d0 = center - timedelta(days=days_range)
        d1 = center + timedelta(days=days_range)
        requested_days = (d1 - d0).days + 1

        if station is None:
            # 1) берём все станции
            all_stations = self._list_all_stations()
            if not all_stations:
                raise RuntimeError(
                    "Не удалось получить список станций автоматически. "
                    "Передайте station явно."
                )

            # 2) фильтруем по наличию файлов в окне (по листингам)
            stations_list = self._filter_available_stations(
                all_stations, d0=d0, d1=d1, min_days_present=min_days_present
            )

            if not stations_list:
                raise RuntimeError(
                    f"Не найдено ни одной станции с >= {min_days_present} днями данных "
                    f"в диапазоне {d0.isoformat()}–{d1.isoformat()}."
                )

            station = stations_list[0]
            print(
                f"Available ionosonde stations for {target_date}: {stations_list}\n"
                f"No station was explicitly specified. Automatically selecting the first available station: {station}"
            )
        else:
            # Если station задана — оставим как раньше: просто качаем её (валидацию по желанию можно вернуть)
            station = station.strip()

        return self._download_for_station(
            station=station,
            target_date=center,
            d0=d0,
            d1=d1,
            requested_days=requested_days,
            days_range=days_range,
            min_days_present=min_days_present,
            filename=filename,
        )

    def _download_for_station(
        self,
        station: str,
        target_date: date,
        d0: date,
        d1: date,
        requested_days: int,
        days_range: int,
        min_days_present: int,
        filename: Optional[str],
    ) -> StationDownloadReport:
        files = self._build_urls_for_date_window(station, target_date, days_range=days_range)

        collected: List[str] = []
        downloaded_days = 0

        for url in files:
            try:
                resp = requests.get(url, headers=self._headers, timeout=self.timeout)
                if resp.status_code != 200:
                    continue
                text = resp.text
                if not text or not text.strip():
                    continue

                collected.append(f"# station={station} url={url}")
                collected.append(text.rstrip("\n"))
                downloaded_days += 1
            except Exception:
                continue

        if downloaded_days < min_days_present:
            return StationDownloadReport(
                station=station,
                start=d0,
                end=d1,
                requested_days=requested_days,
                downloaded_days=downloaded_days,
                output_path=None,
                skipped_reason=(
                    f"Недостаточно данных в окне (downloaded_days={downloaded_days} "
                    f"< min_days_present={min_days_present})"
                ),
            )

        if filename is None:
            filename_local = (
                f"{station}_{self.product}_{self.dataset}_"
                f"{target_date.strftime('%Y%m%d')}.txt"
            )
        else:
            root, ext = os.path.splitext(filename)
            ext = ext or ".txt"
            filename_local = f"{root}_{station}{ext}"

        out_path = self._write_text_file(filename_local, "\n".join(collected) + "\n")

        return StationDownloadReport(
            station=station,
            start=d0,
            end=d1,
            requested_days=requested_days,
            downloaded_days=downloaded_days,
            output_path=out_path,
            skipped_reason=None,
        )
