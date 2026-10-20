"""Download SolarMonitor coronal-hole coordinate files without processing them."""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
BASE_URL = "https://solarmonitor.org/data/"


class CoronalHoleDownloader:
    """Sequential, resumable downloads; only 404/410 mean missing data.

    Use one instance at a time per output directory. By default the date range
    spans the earliest year advertised by the archive through today (UTC).
    """

    def __init__(self, out_dir="files/solarmonitor/data", delay_seconds=3.0):
        if delay_seconds < 3:
            raise ValueError("Use a delay of at least 3 seconds")
        self.out_dir = Path(out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay_seconds
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            "Polar-lights/1.0 (scientific archive download)"
        )
        self._last_request = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.session.close()

    @staticmethod
    def _retry_after_seconds(value):
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(
                    0.0,
                    (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds(),
                )
            except (ValueError, TypeError, OverflowError):
                return None

    def _pause(self, seconds):
        # Deliberately unbounded for server throttling: never hammer the host.
        time.sleep(max(0.0, seconds))
        self._last_request = time.monotonic()

    def _get(self, url):
        """Retry transient failures; honor throttling before trying again."""
        backoff = 30.0
        for attempt in range(3):
            if self._last_request is not None:
                wait = self.delay + random.uniform(0, self.delay / 2)
                self._pause(max(0.0, wait - (time.monotonic() - self._last_request)))
            try:
                response = self.session.get(url, timeout=(15, 90))
            except requests.RequestException:
                if attempt == 2:
                    raise
                self._pause(backoff)
                backoff = min(backoff * 2, 900.0)
                continue

            if response.status_code in (404, 410):
                return response
            if response.status_code in (403, 429):
                # Keep the current date pending and respect the server's throttle.
                wait = self._retry_after_seconds(response.headers.get("Retry-After"))
                self._pause(wait if wait is not None else backoff)
                backoff = min(backoff * 2, 900.0)
                continue
            if response.status_code >= 500:
                if attempt == 2:
                    response.raise_for_status()
                wait = self._retry_after_seconds(response.headers.get("Retry-After"))
                self._pause(wait if wait is not None else backoff)
                backoff = min(backoff * 2, 900.0)
                continue
            response.raise_for_status()
            return response
        raise RuntimeError(f"Temporary request failure after retries: {url}")

    def _log_error(self, day, url, exc):
        line = f"{datetime.now(UTC).isoformat()}\t{day}\t{url}\t{type(exc).__name__}: {exc}\n"
        try:
            with (self.out_dir / "errors.log").open("a", encoding="utf-8") as stream:
                stream.write(line)
        except OSError:
            logger.exception(
                "Could not write errors.log; original error: %s", line.rstrip()
            )
        logger.warning("Skipping %s after error: %s", day, exc)

    def _write_missing(self, missing):
        path = self.out_dir / "missing.txt"
        temporary = path.with_suffix(".txt.part")
        temporary.write_text(
            "".join(f"{day}\n" for day in sorted(missing)), encoding="utf-8"
        )
        temporary.replace(path)

    def download(self, start=None, end=None):
        """Download an inclusive range and continue past individual bad dates.

        Missing (404/410) dates go to missing.txt. Other per-date errors go to
        errors.log and are skipped. HTTP 403/429 are retried with backoff so the
        server has time to accept requests again. Existing files are resumed.
        """
        end = date.fromisoformat(end) if isinstance(end, str) else end
        end = end or datetime.now(UTC).date()
        start = date.fromisoformat(start) if isinstance(start, str) else start
        missing_path = self.out_dir / "missing.txt"
        missing = (
            set(missing_path.read_text(encoding="utf-8").splitlines())
            if missing_path.exists()
            else set()
        )
        self._write_missing(missing)
        stats = {"downloaded": 0, "cached": 0, "missing": 0, "errors": 0}

        # Archive-index failures are retried indefinitely with capped backoff.
        if start is None:
            backoff = 30.0
            while True:
                try:
                    response = self._get(BASE_URL)
                    years = [
                        int(a.get_text(strip=True))
                        for a in BeautifulSoup(
                            response.content, "html.parser"
                        ).find_all("a")
                        if re.fullmatch(r"\d{4}", a.get_text(strip=True))
                    ]
                    if years:
                        start = date(min(years), 1, 1)
                        break
                    raise ValueError("No archive years found in SolarMonitor index")
                except Exception as exc:  # noqa: BLE001 -- keep the archive run alive on any per-request failure
                    self._log_error("archive-index", BASE_URL, exc)
                    self._pause(backoff)
                    backoff = min(backoff * 2, 900.0)

        if start > end:
            raise ValueError("start must be <= end")
        logger.info(
            "SolarMonitor download: %s through %s -> %s", start, end, self.out_dir
        )
        day = start
        while day <= end:
            relative = f"{day:%Y/%m/%d}/meta/arm_ch_location_{day:%Y%m%d}.txt"
            url = BASE_URL + relative
            target = self.out_dir / relative
            key = day.isoformat()
            try:
                if target.is_file() and target.stat().st_size:
                    stats["cached"] += 1
                    if key in missing:
                        missing.remove(key)
                        self._write_missing(missing)
                else:
                    response = self._get(url)
                    if response.status_code in (404, 410):
                        missing.add(key)
                        self._write_missing(missing)
                        stats["missing"] += 1
                        logger.info("Missing: %s", key)
                    else:
                        body = response.content
                        if (
                            not body.strip()
                            or b"<html" in body[:1024].lower()
                            or b"<!doctype html" in body[:1024].lower()
                        ):
                            raise ValueError(
                                f"Empty response or HTML instead of coordinates: {url}"
                            )
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_suffix(target.suffix + ".part")
                        temporary.write_bytes(body)
                        temporary.replace(target)
                        missing.discard(key)
                        self._write_missing(missing)
                        stats["downloaded"] += 1
                        logger.info("Saved: %s", target)
            except Exception as exc:  # noqa: BLE001 -- keep the archive run alive on any per-request failure
                stats["errors"] += 1
                self._log_error(key, url, exc)
            day += timedelta(days=1)

        return {
            **stats,
            "directory": str(self.out_dir),
            "missing_file": str(missing_path),
            "errors_file": str(self.out_dir / "errors.log"),
        }
