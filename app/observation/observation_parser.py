import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from typing import Dict, Optional


class ObservationParser:
    def __init__(self) -> None:
        self.soup: Optional[BeautifulSoup] = None

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
            "Connection": "close",
        })

        retry = Retry(
            total=5,
            connect=5,
            read=5,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def __fetch_html(self, url: str) -> None:
        """
        Скачивает HTML страницы и сохраняет в self.soup
        """
        try:
            resp = self.session.get(url, timeout=(10, 25))
            resp.raise_for_status()
        except requests.exceptions.SSLError as e:
            raise RuntimeError(f"SSL ошибка при запросе {url}: {e}") from e
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"HTTP ошибка при запросе {url}: {e}") from e

        self.soup = BeautifulSoup(resp.text, "html.parser")

    def parse(self, url: str) -> Dict[str, str]:
        self.__fetch_html(url)

        data: Dict[str, str] = {}
        if not self.soup:
            return data

        table = self.soup.find("table")
        if not table:
            return data

        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")
            if not th or not td:
                continue
            data[th.get_text(strip=True)] = td.get_text(strip=True)

        return data