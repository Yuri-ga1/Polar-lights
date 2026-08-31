from __future__ import annotations

import datetime
import random
import time
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class ObservationLinksFinder:
    """Fetch SpaceWeatherLive observation links for a calendar date."""

    MIN_REQUEST_DELAY = 10.0
    MAX_REQUEST_DELAY = 20.0
    MAX_ATTEMPTS = 3

    def __init__(self, base_url: str = "https://www.spaceweatherlive.com", session: Optional[requests.Session] = None, timeout: float = 10.0, lang: str = "EN", max_attempts: int = MAX_ATTEMPTS) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.lang = lang
        self.max_attempts = max(1, max_attempts)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"})

    @staticmethod
    def _date_to_param(date_str: str) -> str:
        return datetime.datetime.strptime(date_str, "%Y/%m/%d").strftime("%Y%m%d")

    def close(self) -> None:
        return

    def _request(self, url: str, **kwargs) -> Optional[requests.Response]:
        for attempt in range(1, self.max_attempts + 1):
            delay = random.uniform(self.MIN_REQUEST_DELAY, self.MAX_REQUEST_DELAY)
            print(
                f"SpaceWeatherLive request {attempt}/{self.max_attempts}: "
                f"waiting {delay:.1f}s before {url}"
            )
            time.sleep(delay)
            try:
                response = self.session.get(url, **kwargs)
                if response.status_code == 200:
                    return response
                error = f"HTTP {response.status_code}"
            except requests.RequestException as exc:
                error = str(exc)

            if attempt == self.max_attempts:
                print(
                    f"SpaceWeatherLive: failed to get data from {url} after "
                    f"{self.max_attempts} attempts ({error}). Continuing."
                )
        return None

    def _fetch_observations_payload(self, date_str: str) -> Optional[dict]:
        param = self._date_to_param(date_str)
        referer = f"{self.base_url}/en/archive/{date_str}/observations.html"
        try:
            self._request(referer, timeout=self.timeout)
            response = self._request(
                f"{self.base_url}/includes/live-data.php",
                params={"object": "getObservations", "lang": self.lang, "param": param},
                headers={"Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest", "Referer": referer, "Origin": self.base_url},
                timeout=self.timeout,
            )
            if response is None:
                return None
            return response.json()
        except ValueError as exc:
            print(
                f"SpaceWeatherLive: invalid response for {date_str}: {exc}. "
                "Continuing without observations."
            )
            return None

    def get_observation_count(self, date_str: str) -> Optional[int]:
        payload = self._fetch_observations_payload(date_str)
        features = payload.get("features") if payload else None
        return len(features) if isinstance(features, list) else None

    def get_observation_links(self, date_str: str) -> List[str]:
        payload = self._fetch_observations_payload(date_str)
        features = payload.get("features") if payload else None
        if not isinstance(features, list):
            return []
        links = []
        for feature in features:
            html = (feature.get("properties") or {}).get("html") or ""
            anchor = BeautifulSoup(html, "html.parser").find("a", href=True)
            if anchor:
                links.append(urljoin(self.base_url + "/", anchor["href"]))
        return list(dict.fromkeys(links))
