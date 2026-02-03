from __future__ import annotations

from urllib.parse import urlencode
from datetime import datetime

from app.base_classes.base_downloader import BaseDownloader


class GimDownloader(BaseDownloader):
    """Скачивает файлы GIM по прямой ссылке Simurg."""

    BASE_URL = "https://api.simurg.space/datafiles/gim"

    def __init__(self, out_dir: str = ".", gim_type: str = "uqrg") -> None:
        super().__init__(out_dir=out_dir)
        self.gim_type = gim_type.lower()

    @staticmethod
    def _build_filename(date_str: str, gim_type: str) -> str:
        """
        Строит имя файла в формате:
        uqrg3160.25i
        """
        date = datetime.strptime(date_str, "%Y-%m-%d")

        doy = date.timetuple().tm_yday
        year_short = date.year % 100
        session = 0

        return f"{gim_type}{doy:03d}{session}.{year_short:02d}i"

    def download(self, date_str: str) -> str:
        params = urlencode({"d": date_str, "gim_type": self.gim_type})
        url = f"{self.BASE_URL}?{params}"

        filename = self._build_filename(
            date_str=date_str,
            gim_type=self.gim_type,
        )

        return self._download_result(url=url, filename=filename)
