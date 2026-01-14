from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, Optional

import requests


class KyotoDstDownloader:
    """Загружает месячный файл индекса Dst из WDC Kyoto."""

    DEFAULT_VERSIONS: tuple[str, ...] = ("dst_realtime", "dst_provisional", "dst_final")

    def __init__(self, out_dir: str = ".") -> None:
        self.out_dir = out_dir
        os.makedirs(self.out_dir, exist_ok=True)

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

    def download(self, date_str: str, filename: Optional[str] = None,
                 versions: Optional[Iterable[str]] = None) -> str:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        try_versions = list(versions) if versions is not None else list(self.DEFAULT_VERSIONS)
        urls = self._build_urls(date, try_versions)
        last_exc: Optional[Exception] = None
        for url in urls:
            try:
                resp = requests.get(url, timeout=60)
                if resp.status_code == 200:
                    data = resp.text
                    if not data.strip():
                        raise RuntimeError(f"Получен пустой файл с {url}")
                    if filename is None:
                        save_name = f"dst_{date.strftime('%Y%m')}.for"
                    else:
                        save_name = filename
                    file_path = os.path.join(self.out_dir, save_name)
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(data)
                    return file_path
            except Exception as exc:
                last_exc = exc
                continue
        raise RuntimeError(
            f"Не удалось загрузить Dst из WDC Kyoto для {date_str}. "
            f"Попробованы каталоги: {', '.join(try_versions)}. Последняя ошибка: {last_exc}"
        )
