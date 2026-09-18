from __future__ import annotations

import json
import logging
from pathlib import Path

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.base_classes.base_downloader import BaseDownloader
from app.solar.models import SolarDiskConfig, utc_datetime
from app.solar.srs_parser import parse_srs

logger = logging.getLogger(__name__)
HELIOVIEWER = "https://api.helioviewer.org/v2/"
NOAA_SRS = "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/solar_region_summaries/"


class SolarDownloadError(RuntimeError):
    """An unavailable or invalid solar source product."""


class SolarDownloader(BaseDownloader):
    """Use the existing file-cache base with bounded HTTP retries, not endless polling."""

    def __init__(self, config: SolarDiskConfig):
        super().__init__(str(config.cache_dir))
        self.config = config
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
        self.session.headers["User-Agent"] = (
            "Polar-lights/1.0 (solar-disk scientific visualization)"
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()

    def fetch(self, url, *, params=None, types=()):
        try:
            response = self.session.get(url, params=params, timeout=(15, 90))
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SolarDownloadError(f"Could not download {url}: {exc}") from exc
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
        if not response.content or content_type not in types:
            raise SolarDownloadError(
                f"Invalid response from {response.url}: type={content_type!r}, size={len(response.content)}"
            )
        return response

    def cached(self, name: str) -> Path | None:
        path = None if self.config.force_download else self._get_existing_file(name)
        return Path(path) if path else None

    def write_bytes(self, name: str, content: bytes) -> Path:
        target = Path(self.out_dir) / name
        temporary = target.with_suffix(target.suffix + ".part")
        temporary.write_bytes(content)
        temporary.replace(target)
        return target

    def write_json(self, name, value):
        return self.write_bytes(name, json.dumps(value, indent=2).encode())


class HelioviewerDownloader(SolarDownloader):
    def download(self):
        requested = self.config.requested_time
        name = f"closest_{self.config.source_id}_{requested:%Y%m%dT%H%M%S%fZ}.json"
        cached = self.cached(name)
        if cached:
            closest = json.loads(cached.read_text())
        else:
            response = self.fetch(
                HELIOVIEWER + "getClosestImage/",
                params={
                    "date": requested.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sourceId": self.config.source_id,
                },
                types=("application/json",),
            )
            closest = response.json()
            if "id" not in closest or "date" not in closest:
                raise SolarDownloadError(f"No HMI frame found: {closest}")
            self.write_json(name, closest)
        actual = utc_datetime(closest["date"])
        if (
            abs((actual - requested).total_seconds())
            > self.config.max_time_delta_minutes * 60
        ):
            raise SolarDownloadError(
                f"Nearest HMI frame is {actual.isoformat()}, outside the allowed {self.config.max_time_delta_minutes:g} minutes from {requested.isoformat()}"
            )
        image_id = int(closest["id"])
        name = f"hmi_{image_id}.jp2"
        jp2_path = self.cached(name)
        params = {
            "date": actual.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sourceId": self.config.source_id,
        }
        jp2_url = (
            requests.Request("GET", HELIOVIEWER + "getJP2Image/", params=params)
            .prepare()
            .url
        )
        if not jp2_path:
            response = self.fetch(
                HELIOVIEWER + "getJP2Image/",
                params=params,
                types=(
                    "image/jp2",
                    "image/jpeg2000",
                    "application/octet-stream",
                    "application/jp2",
                ),
            )
            jp2_path = self.write_bytes(name, response.content)
        try:
            with Image.open(jp2_path) as image:
                if image.format != "JPEG2000" or image.size != (
                    int(closest["width"]),
                    int(closest["height"]),
                ):
                    raise ValueError("Unexpected format or dimensions")
                image.load()
        except (OSError, ValueError) as exc:
            raise SolarDownloadError(
                f"Unreadable JP2 {jp2_path}; retry with force_download=True: {exc}"
            ) from exc
        return closest, jp2_path, jp2_url

    def header(self, image_id: int) -> Path:
        name = f"hmi_{int(image_id)}.xml"
        path = self.cached(name)
        if path:
            return path
        response = self.fetch(
            HELIOVIEWER + "getJP2Header/",
            params={"id": int(image_id)},
            types=("text/xml", "application/xml"),
        )
        return self.write_bytes(name, response.content)


class SRSDownloader(SolarDownloader):
    def download(self, day):
        name = f"{day:%Y%m%d}SRS.txt"
        provenance_name = name + ".json"
        path, provenance = self.cached(name), self.cached(provenance_name)
        if path and provenance:
            report = parse_srs(path.read_text())
            if report.issued.date() != day:
                raise SolarDownloadError(f"Cached SRS date mismatch: {path}")
            metadata = json.loads(provenance.read_text())
            if not metadata["fallback"] or self.config.allow_srs_fallback:
                if metadata["fallback"]:
                    logger.warning("Using cached fallback SRS: %s", metadata["url"])
                return report, metadata
        sources = [("NOAA/NCEI SWPC SRS archive", f"{NOAA_SRS}{day:%Y/%m}/{name}")]
        if self.config.allow_srs_fallback:
            sources.append(
                (
                    "SolarMonitor mirror of NOAA SRS (fallback)",
                    f"https://www.solarmonitor.org/data/{day:%Y/%m/%d}/meta/{day:%m%d}SRS.txt",
                )
            )
        failures = []
        for index, (source, url) in enumerate(sources):
            try:
                response = self.fetch(
                    url, types=("text/plain", "application/octet-stream")
                )
                report = parse_srs(response.text)
                if report.issued.date() != day:
                    raise ValueError(f"Expected {day}, got SRS issued {report.issued}")
                provenance = {
                    "source": source,
                    "url": response.url,
                    "fallback": bool(index),
                    "issued": report.issued.isoformat(),
                    "coordinate_epoch": report.epoch.isoformat(),
                }
                self.write_bytes(name, response.content)
                self.write_json(provenance_name, provenance)
                return report, provenance
            except (SolarDownloadError, ValueError) as exc:
                failures.append(str(exc))
                logger.warning("SRS source %s failed: %s", source, exc)
        raise SolarDownloadError("No historical SRS available: " + "; ".join(failures))
