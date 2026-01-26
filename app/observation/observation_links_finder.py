from __future__ import annotations

import datetime
import re
from typing import List, Optional

import requests
from bs4 import BeautifulSoup


class ObservationLinksFinder:
    """Scraper for SpaceWeatherLive observation links.

    Parameters
    ----------
    base_url : str, optional
        The root of the SpaceWeatherLive site.  Defaults to the official
        ``https://www.spaceweatherlive.com``.  Set this to
        ``https://www.spaceweather.live`` if you prefer the alternative
        TLD.
    session : Optional[requests.Session], optional
        An optional preconfigured ``requests.Session``.  If not
        provided, a new session will be created with a sensible
        desktop user–agent.
    max_consecutive_errors : int, optional
        When discovering pages without a known observation count, stop
        the enumeration loop after this many consecutive non‑matching
        pages **after** at least one valid page has been found.  The
        default of ``50`` is conservative enough to tolerate gaps in
        global observation IDs without wasting too many requests.
    timeout : float, optional
        Network timeout in seconds for each HTTP request.  Defaults to 10.
    """

    count_pattern = re.compile(
        r"(\d+)\s+observations were shared by aurora chasers for this day",
        re.IGNORECASE,
    )

    heading_date_pattern = re.compile(
        r"on\s+[^,]+,\s+(\d+\s+\w+\s+\d{4})",  # e.g. "on Monday, 19 January 2026"
        re.IGNORECASE,
    )

    def __init__(
        self,
        base_url: str = "https://www.spaceweatherlive.com",
        session: Optional[requests.Session] = None,
        max_consecutive_errors: int = 50,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_consecutive_errors = max_consecutive_errors
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
    def _human_date(date_str: str) -> str:
        """Convert ``YYYY/MM/DD`` into ``D Month YYYY``.

        The site uses English month names in headings, so this helper
        ensures the same format.  Leading zeros on the day are dropped.
        """
        dt = datetime.datetime.strptime(date_str, "%Y/%m/%d")
        return dt.strftime("%-d %B %Y")

    def _get_raw_page(self, url: str) -> Optional[str]:
        """Return the text of ``url`` or ``None`` on errors.

        This helper centralises exception handling for network issues.
        It respects the configured timeout.
        """
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException:
            pass
        return None

    def get_observation_count(self, date_str: str) -> Optional[int]:
        """Attempt to extract the observation count from the daily page.

        Some daily observation pages include a meta description such as
        "111 observations were shared by aurora chasers for this day".  If
        that string is present, the number of observations can be
        determined without loading the JavaScript map.  This method
        performs a standard HTTP GET to fetch the raw HTML and uses a
        regex to search for that phrase.  If found, the integer count
        is returned; otherwise ``None`` is returned.

        Parameters
        ----------
        date_str : str
            The date string in ``YYYY/MM/DD`` format.

        Returns
        -------
        Optional[int]
            The number of observations for the specified date if
            discoverable, otherwise ``None``.
        """
        url = f"{self.base_url}/en/archive/{date_str}/observations.html"
        html = self._get_raw_page(url)
        if not html:
            return None
        match = self.count_pattern.search(html)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        return None

    def _page_matches_date(self, html: str, human_date: str) -> bool:
        """Return ``True`` if the observation page contains the target date.

        Each observation page includes a heading like "Aurora Observation
        by Maria on Monday, 19 January 2026 around ..."【385249715917304†L80-L92】.
        This method extracts the date portion from that heading using
        ``heading_date_pattern`` and compares it to ``human_date``.  If
        no heading is found or the dates don't match, the page is
        considered not relevant.
        """
        heading_match = self.heading_date_pattern.search(html)
        if heading_match:
            extracted = heading_match.group(1).strip()
            return extracted.lower() == human_date.lower()
        
        return human_date.lower() in html.lower()

    def get_observation_links(self, date_str: str) -> List[str]:
        """Return a list of observation URLs for the given date.

        The method first attempts to determine how many observations exist
        using :meth:`get_observation_count`.  If that fails, it enters
        an enumeration loop that walks through observation IDs and
        collects pages whose heading matches the target date.  The loop
        stops when it has found the expected number of observations or
        when it has encountered ``max_consecutive_errors`` consecutive
        unsuccessful attempts after at least one success.  If no
        observations are found at all, the method still returns an empty
        list without raising.

        Parameters
        ----------
        date_str : str
            The date in ``YYYY/MM/DD`` notation.

        Returns
        -------
        List[str]
            A list of fully qualified URLs pointing to each observation
            page for ``date_str``.
        """
        human_date = self._human_date(date_str)
        observation_count = self.get_observation_count(date_str)
        links: List[str] = []
        
        if observation_count and observation_count > 0:
            current_id = 0
            consecutive_errors = 0
            while len(links) < observation_count and consecutive_errors < self.max_consecutive_errors:
                url = f"{self.base_url}/en/archive/{date_str}/observations/{current_id}.html"
                html = self._get_raw_page(url)
                if html and self._page_matches_date(html, human_date):
                    links.append(url)
                    consecutive_errors = 0
                else:
                    consecutive_errors += 1
                current_id += 1
            return links
        
        current_id = 0
        consecutive_errors = 0
        while consecutive_errors < self.max_consecutive_errors:
            url = f"{self.base_url}/en/archive/{date_str}/observations/{current_id}.html"
            html = self._get_raw_page(url)
            if html and self._page_matches_date(html, human_date):
                links.append(url)
                consecutive_errors = 0
            else:
                consecutive_errors += 1
            current_id += 1
        return links
