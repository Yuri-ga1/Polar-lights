from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable
import gzip
import re

import requests


DEFAULT_USER_AGENT = "PolarLightsDataFetcher/1.0"


@dataclass
class HttpDownloader:
    base_dir: Path
    user_agent: str = DEFAULT_USER_AGENT
    timeout: int = 30
    trust_env: bool = True
    session: requests.Session = field(default_factory=requests.Session)

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        self.session.headers.update({"User-Agent": self.user_agent})
        self.session.trust_env = self.trust_env

    def download_bytes(self, url: str) -> bytes:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.content

    def download_text(self, url: str, encoding: str | None = None) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        if encoding:
            response.encoding = encoding
        return response.text

    def save_bytes(self, data: bytes, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def save_text(self, data: str, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")
        return path


@dataclass
class DstDownloader(HttpDownloader):
    base_url: str = "https://wdc.kugi.kyoto-u.ac.jp/dst_final"
    file_template: str = "dst{yy}{month:02d}.for.request"
    directory_template: str = "{year}{month:02d}"

    def build_monthly_url(self, target_date: date) -> str:
        directory = self.directory_template.format(year=target_date.year, month=target_date.month)
        filename = self.file_template.format(yy=str(target_date.year)[-2:], month=target_date.month)
        return f"{self.base_url}/{directory}/{filename}"

    def download_day(self, target_date: date, dest_dir: Path | None = None) -> Path:
        url = self.build_monthly_url(target_date)
        content = self.download_text(url)
        line = self._extract_daily_line(content, target_date)
        if not line:
            raise ValueError(f"DST line not found for {target_date.isoformat()} in {url}")

        output_dir = dest_dir or self.base_dir
        output_name = f"dst_{target_date.strftime('%Y%m%d')}.txt"
        return self.save_text(f"{line}\n", Path(output_dir) / output_name)

    @staticmethod
    def _extract_daily_line(content: str, target_date: date) -> str | None:
        for line in content.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            numbers = [int(val) for val in re.findall(r"-?\d+", line)]
            if len(numbers) < 4:
                continue
            if numbers[0] >= 1900 and len(numbers) >= 3:
                year, month, day = numbers[0], numbers[1], numbers[2]
            else:
                year, month, day = target_date.year, target_date.month, numbers[0]
            if (year, month, day) == (target_date.year, target_date.month, target_date.day):
                return line
        return None


@dataclass
class OmniWebDownloader(HttpDownloader):
    base_url: str = "https://omniweb.gsfc.nasa.gov/cgi/nx1.cgi"
    resource: str = "omni_min"
    default_variables: tuple[str, ...] = (
        "SYM_H",
        "BX_GSE",
        "BY_GSM",
        "BZ_GSM",
        "Vx",
        "Vy",
        "Vz",
        "N",
        "T",
    )

    def build_query(self, target_date: date, variables: Iterable[str]) -> list[tuple[str, str]]:
        date_str = target_date.strftime("%Y%m%d")
        params: list[tuple[str, str]] = [
            ("activity", "retrieve"),
            ("res", self.resource),
            ("start_date", date_str),
            ("end_date", date_str),
        ]
        params.extend(("vars", var) for var in variables)
        return params

    def download_day(
        self,
        target_date: date,
        dest_dir: Path | None = None,
        variables: Iterable[str] | None = None,
    ) -> Path:
        vars_to_request = tuple(variables) if variables is not None else self.default_variables
        query = self.build_query(target_date, vars_to_request)
        response = self.session.get(self.base_url, params=query, timeout=self.timeout)
        response.raise_for_status()

        output_dir = dest_dir or self.base_dir
        output_name = f"omni_{target_date.strftime('%Y%m%d')}.txt"
        return self.save_text(response.text, Path(output_dir) / output_name)


@dataclass
class GimDownloader(HttpDownloader):
    base_url: str = "https://cddis.nasa.gov/archive/gnss/products/ionex"
    analysis_center: str = "uqrg"
    file_template: str = "{center}{doy:03d}0.{yy}i.Z"

    def build_daily_url(self, target_date: date) -> str:
        doy = target_date.timetuple().tm_yday
        filename = self.file_template.format(center=self.analysis_center, doy=doy, yy=str(target_date.year)[-2:])
        return f"{self.base_url}/{target_date.year}/{doy:03d}/{filename}"

    def download_day(
        self,
        target_date: date,
        dest_dir: Path | None = None,
        decompress: bool = True,
    ) -> Path:
        url = self.build_daily_url(target_date)
        data = self.download_bytes(url)
        output_dir = dest_dir or self.base_dir
        filename = Path(url).name
        compressed_path = self.save_bytes(data, Path(output_dir) / filename)

        if not decompress:
            return compressed_path

        if compressed_path.suffix == ".gz":
            decompressed = gzip.decompress(compressed_path.read_bytes())
        elif compressed_path.suffix == ".Z":
            try:
                from unlzw3 import unlzw
            except ModuleNotFoundError:
                return compressed_path

            decompressed = unlzw(compressed_path.read_bytes())
        else:
            return compressed_path

        decompressed_path = compressed_path.with_suffix("")
        return self.save_bytes(decompressed, decompressed_path)
