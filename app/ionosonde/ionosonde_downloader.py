from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

import requests

from app.base_classes.base_downloader import BaseDownloader


class TemporaryNetworkError(Exception):
    """Temporary network-related error."""
    pass


class DataFetchError(Exception):
    """Non-retryable data fetch error."""
    pass


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
    BASE_URL: str = "https://lgdc.uml.edu/common/DIDBGetValues"
    STATIONS_PAGE: str = "https://giro.uml.edu/didbase/scaled.php"

    def __init__(
        self,
        out_dir: str = ".",
        timeout: float = 60.0,
    ) -> None:
        super().__init__(out_dir=out_dir)
        self.timeout = timeout

        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        }

        self._session = requests.Session()
        self._session.headers.update(self._headers)

        self._availability_cache: Dict[Tuple[str, str], Set[str]] = {}

    # -------------------------
    # date helpers
    # -------------------------

    @staticmethod
    def _parse_date(d: Union[str, date, datetime]) -> date:
        """Normalize input value to date."""
        if isinstance(d, date) and not isinstance(d, datetime):
            return d
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, str):
            return datetime.strptime(d, "%Y-%m-%d").date()
        raise TypeError(f"Дата должна быть str/date/datetime, получено: {type(d)!r}")

    @staticmethod
    def _daterange(d0: date, d1: date) -> Iterable[date]:
        cur = d0
        while cur <= d1:
            yield cur
            cur += timedelta(days=1)

    # -------------------------
    # http helpers
    # -------------------------

    def _get_with_retries(
        self,
        url: str,
        max_attempts: int = 5,
        base_delay: float = 1.5,
    ) -> requests.Response:
        """Perform GET request with retries for temporary network/server errors."""
        last_exc: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self._session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return resp

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as exc:
                last_exc = exc
                if attempt == max_attempts:
                    raise TemporaryNetworkError(str(exc)) from exc
                time.sleep(base_delay * attempt)

            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None

                if status is not None and 500 <= status < 600:
                    last_exc = exc
                    if attempt == max_attempts:
                        raise TemporaryNetworkError(f"HTTP {status}: {exc}") from exc
                    time.sleep(base_delay * attempt)
                    continue

                raise DataFetchError(str(exc)) from exc

            except requests.RequestException as exc:
                raise DataFetchError(str(exc)) from exc

        raise TemporaryNetworkError(str(last_exc))

    def _get_text(self, url: str) -> str:
        """Fetch URL and return text content."""
        resp = self._get_with_retries(url)
        return resp.text

    # -------------------------
    # station discovery
    # -------------------------

    def _list_all_stations(self) -> List[str]:
        """Retrieve valid URSI station codes from GIRO page."""
        try:
            html = self._get_text(self.STATIONS_PAGE)
        except Exception:
            return []

        # URSI station codes look like IF843, MO155 etc.
        codes = re.findall(r"\(([A-Z]{2}\d{3})\)", html)

        seen: Set[str] = set()
        ordered: List[str] = []

        for code in codes:
            if code not in seen:
                seen.add(code)
                ordered.append(code)

        return ordered

    # -------------------------
    # availability check
    # -------------------------

    def _build_query_url(
        self,
        station: str,
        from_dt: datetime,
        to_dt: datetime,
        char_names: Iterable[str],
        dmuf: int = 3000,
    ) -> str:
        """Build GIRO query URL preserving current URL format."""
        from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%S")
        to_str = to_dt.strftime("%Y-%m-%dT%H:%M:%S")
        char_params = ",".join(list(char_names))

        params = [
            f"ursiCode={station}",
            f"charName={char_params}",
            f"DMUF={dmuf}",
            f"fromDate={from_str}",
            f"toDate={to_str}",
        ]
        return f"{self.BASE_URL}?{'&'.join(params)}"

    def _fetch_data_text(
        self,
        station: str,
        from_dt: datetime,
        to_dt: datetime,
        char_names: Iterable[str],
        dmuf: int,
    ) -> str:
        """Fetch data text from GIRO with retries."""
        url = self._build_query_url(station, from_dt, to_dt, char_names, dmuf)
        resp = self._get_with_retries(url)
        return resp.text

    def _parse_unique_days(self, data_text: str) -> Set[str]:
        """Extract unique YYYY-MM-DD dates from GIRO response."""
        unique_days: Set[str] = set()

        for line in data_text.splitlines():
            if not line or line.startswith("#"):
                continue

            parts = line.split()
            if not parts:
                continue

            ts = parts[0]
            if len(ts) >= 10:
                day_str = ts[:10]
                if day_str != "---":
                    unique_days.add(day_str)

        return unique_days

    def _station_has_min_days(
        self,
        station: str,
        d0: date,
        d1: date,
        min_days_present: int,
        char_names: Iterable[str],
        dmuf: int,
    ) -> bool:
        """Check whether station has enough data days in the requested range."""
        from_dt = datetime.combine(d0, datetime.min.time())
        to_dt = datetime.combine(d1, datetime.max.time().replace(microsecond=0))

        text = self._fetch_data_text(station, from_dt, to_dt, char_names, dmuf)
        unique_days = self._parse_unique_days(text)
        return len(unique_days) >= min_days_present

    # -------------------------
    # public API
    # -------------------------

    def download(
        self,
        target_date: Union[str, date, datetime],
        char_names: Iterable[str] = ['foF2', 'hmF2'],
        station: Optional[str] = None,
        days_range: int = 13,
        min_days_present: int = 1,
        filename: Optional[str] = None,
        dmuf: int = 3000,
    ) -> StationDownloadReport:
        """Download ionosonde data for target date and station."""
        center = self._parse_date(target_date)
        d0 = center - timedelta(days=days_range)
        d1 = center + timedelta(days=days_range)
        requested_days = (d1 - d0).days + 1

        chars_list = list(char_names)

        selected_station: Optional[str] = None

        if station is None:
            all_stations = self._list_all_stations()
            if not all_stations:
                raise RuntimeError(
                    "Не удалось получить список станций автоматически. "
                    "Передайте station явно."
                )

            network_errors = 0

            for st in all_stations:
                try:
                    if self._station_has_min_days(
                        st, d0, d1, min_days_present, chars_list, dmuf
                    ):
                        selected_station = st
                        break

                except TemporaryNetworkError as exc:
                    network_errors += 1
                    # print(f"Temporary network error for station {st}: {exc}")
                    continue

                except DataFetchError as exc:
                    # print(f"Data fetch error for station {st}: {exc}")
                    continue

                except Exception as exc:
                    # print(f"Unexpected error for station {st}: {exc}")
                    continue

            if selected_station is None:
                if network_errors > 0:
                    raise RuntimeError(
                        "Не удалось автоматически выбрать станцию: "
                        "во время проверки были временные сетевые ошибки при обращении к GIRO."
                    )

                raise RuntimeError(
                    f"Не найдено ни одной станции с >= {min_days_present} днями данных "
                    f"в диапазоне {d0.isoformat()}–{d1.isoformat()}."
                )
        else:
            selected_station = station.strip().upper()

        return self._download_for_station(
            station=selected_station,
            center=center,
            d0=d0,
            d1=d1,
            requested_days=requested_days,
            min_days_present=min_days_present,
            filename=filename,
            char_names=chars_list,
            dmuf=dmuf,
        )

    def _download_for_station(
        self,
        station: str,
        center: date,
        d0: date,
        d1: date,
        requested_days: int,
        min_days_present: int,
        filename: Optional[str],
        char_names: Iterable[str],
        dmuf: int,
    ) -> StationDownloadReport:
        """Download data for explicitly selected station."""
        if filename is None:
            filename_local = (
                f"{station}_{'_'.join(char_names)}_"
                f"{center.strftime('%Y%m%d')}.txt"
            )
        else:
            root, ext = os.path.splitext(filename)
            ext = ext or ".txt"
            filename_local = f"{root}_{station}{ext}"

        existing_file = self._get_existing_file(filename_local)
        if existing_file:
            return StationDownloadReport(
                station=station,
                start=d0,
                end=d1,
                requested_days=requested_days,
                downloaded_days=requested_days,
                output_path=existing_file,
                skipped_reason=None,
            )

        from_dt = datetime.combine(d0, datetime.min.time())
        to_dt = datetime.combine(d1, datetime.max.time().replace(microsecond=0))

        try:
            text = self._fetch_data_text(station, from_dt, to_dt, char_names, dmuf)

        except TemporaryNetworkError as exc:
            return StationDownloadReport(
                station=station,
                start=d0,
                end=d1,
                requested_days=requested_days,
                downloaded_days=0,
                output_path=None,
                skipped_reason=f"Временная сетевая ошибка при загрузке данных: {exc}",
            )

        except Exception as exc:
            return StationDownloadReport(
                station=station,
                start=d0,
                end=d1,
                requested_days=requested_days,
                downloaded_days=0,
                output_path=None,
                skipped_reason=f"Ошибка загрузки данных: {exc}",
            )

        unique_days = self._parse_unique_days(text)
        downloaded_days = len(unique_days)

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

        out_path = self._write_text_file(filename_local, text)

        return StationDownloadReport(
            station=station,
            start=d0,
            end=d1,
            requested_days=requested_days,
            downloaded_days=downloaded_days,
            output_path=out_path,
            skipped_reason=None,
        )
