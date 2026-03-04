from __future__ import annotations

import datetime
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


class ObservationLinksFinder:
    """Scraper for SpaceWeatherLive observation links (no Selenium).

    Uses the live-data endpoint:
    /includes/live-data.php?object=getObservations&lang=EN&param=YYYYMMDD
    """

    def __init__(
        self,
        base_url: str = "https://www.spaceweatherlive.com",
        session: Optional[requests.Session] = None,
        timeout: float = 10.0,
        lang: str = "EN",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.lang = lang

        if session is None:
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/105.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                }
            )
        self.session = session

    @staticmethod
    def _date_to_param(date_str: str) -> str:
        """Convert YYYY/MM/DD -> YYYYMMDD used by the live-data endpoint."""
        dt = datetime.datetime.strptime(date_str, "%Y/%m/%d")
        return dt.strftime("%Y%m%d")

    def close(self) -> None:
        """Kept for API compatibility (no driver anymore)."""
        return

    def _fetch_observations_payload(self, date_str: str) -> Optional[dict]:
        """Fetch GeoJSON-like payload from SpaceWeatherLive live-data endpoint."""
        param = self._date_to_param(date_str)

        referer = f"{self.base_url}/en/archive/{date_str}/observations.html"

        try:
            self.session.get(referer, timeout=self.timeout)
        except requests.RequestException:
            pass

        url = f"{self.base_url}/includes/live-data.php"
        params = {"object": "getObservations", "lang": self.lang, "param": param}

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "Origin": self.base_url,
        }

        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)

            if resp.status_code != 200:
                return None
            return resp.json()

        except (requests.RequestException, ValueError):
            return None

    def get_observation_count(self, date_str: str) -> Optional[int]:
        payload = self._fetch_observations_payload(date_str)
        if not payload:
            return None
        feats = payload.get("features")
        if isinstance(feats, list):
            return len(feats)
        return None

    def get_observation_links(self, date_str: str) -> List[str]:
        """Return a list of observation URLs for the given date.

        Matches the old public behavior: returns fully qualified URLs.
        Returns [] on any failure.
        """
        payload = self._fetch_observations_payload(date_str)
        if not payload:
            return []

        feats = payload.get("features")
        if not isinstance(feats, list) or not feats:
            return []

        links: List[str] = []

        for feat in feats:
            props = feat.get("properties") or {}
            html = props.get("html") or ""
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            a = soup.find("a", href=True)
            if not a:
                continue

            href = a["href"]
            full_url = urljoin(self.base_url + "/", href)
            links.append(full_url)

        seen = set()
        uniq: List[str] = []
        for u in links:
            if u not in seen:
                seen.add(u)
                uniq.append(u)

        return uniq