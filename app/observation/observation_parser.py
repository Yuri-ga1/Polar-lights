from __future__ import annotations

import random
import time
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class ObservationParser:
    MIN_REQUEST_DELAY = 10.0
    MAX_REQUEST_DELAY = 20.0
    MAX_ATTEMPTS = 3

    def __init__(self, max_attempts: int = MAX_ATTEMPTS) -> None:
        self.soup: Optional[BeautifulSoup] = None
        self.max_attempts = max(1, max_attempts)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"})
        # Retries are handled below so every attempt observes the 10-20s delay.
        retry = Retry(total=0)
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def parse(self, url: str) -> Dict[str, str]:
        response = None
        last_error = "unknown error"
        for attempt in range(1, self.max_attempts + 1):
            delay = random.uniform(self.MIN_REQUEST_DELAY, self.MAX_REQUEST_DELAY)
            print(
                f"SpaceWeatherLive request {attempt}/{self.max_attempts}: "
                f"waiting {delay:.1f}s before {url}"
            )
            time.sleep(delay)
            try:
                response = self.session.get(url, timeout=(10, 25))
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as exc:
                last_error = str(exc)

        if response is None or response.status_code >= 400:
            message = (
                f"SpaceWeatherLive: failed to get observation {url} after "
                f"{self.max_attempts} attempts ({last_error}). "
                "The caller will stop downloading further observations."
            )
            print(message)
            raise RuntimeError(message)

        table = BeautifulSoup(response.text, "html.parser").find("table")
        if not table:
            return {}
        return {
            row.find("th").get_text(strip=True): row.find("td").get_text(strip=True)
            for row in table.find_all("tr")
            if row.find("th") and row.find("td")
        }
