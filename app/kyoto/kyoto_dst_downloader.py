from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import requests

from app.base_classes.base_downloader import BaseDownloader

from app.logging_config import logged_stage
from app.storage.raw_retention import raw_locked


class KyotoDstDownloader(BaseDownloader):
    """Загружает месячный файл индекса Dst из WDC Kyoto."""

    DEFAULT_VERSIONS: tuple[str, ...] = ("dst_realtime", "dst_provisional", "dst_final")

    def __init__(self, out_dir: str = ".") -> None:
        super().__init__(out_dir=out_dir)

    def _build_urls(self, date: datetime, versions: Iterable[str]) -> list[str]:
        year_full = date.year
        month = date.month
        yyyymm = f"{year_full:04d}{month:02d}"
        yy = year_full % 100
        yymm = f"{yy:02d}{month:02d}"
        urls: list[str] = []
        for ver in versions:
            base = f"https://wdc.kugi.kyoto-u.ac.jp/{ver}/{yyyymm}/dst{yymm}.for.request"
            urls.append(base)
        return urls

    @staticmethod
    def _validate_text(text: str, date: datetime) -> None:
        from app.kyoto.kyoto_dst_processor import KyotoProcessor

        for line in text.splitlines():
            rows = KyotoProcessor._parse_line(line)
            if rows:
                timestamp = rows[0]["datetime"]
                if (timestamp.year, timestamp.month) == (date.year, date.month):
                    return
        raise RuntimeError(
            f"Ответ WDC Kyoto не содержит записей Dst за {date:%Y-%m}"
        )

    @logged_stage("download", entry=False)
    @raw_locked
    def download(self, date_str: str, filename: Optional[str] = None,
                 versions: Optional[Iterable[str]] = None) -> str:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        save_name = filename or f"dst_{date.strftime('%Y%m')}.for"
        existing_file = self._get_existing_file(save_name)
        if existing_file:
            try:
                self._validate_text(Path(existing_file).read_text(encoding="utf-8"), date)
                return existing_file
            except (OSError, UnicodeError, RuntimeError):
                pass

        try_versions = list(versions) if versions is not None else list(self.DEFAULT_VERSIONS)
        urls = self._build_urls(date, try_versions)
        last_exc: Optional[Exception] = None
        for url in urls:
            try:
                resp = requests.get(url, timeout=60)
                resp.raise_for_status()
                data = resp.text
                self._validate_text(data, date)
            except (requests.RequestException, RuntimeError) as exc:
                last_exc = exc
                continue
            return self._write_text_file(save_name, data)
        raise RuntimeError(
            f"Не удалось загрузить Dst из WDC Kyoto для {date_str}. "
            f"Попробованы каталоги: {', '.join(try_versions)}. Последняя ошибка: {last_exc}"
        )
