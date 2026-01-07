import requests
from bs4 import BeautifulSoup
from typing import Dict


class ObservationParser:
    def __init__(self):
        self.soup = None

    def __fetch_html(self, url: str):
        """
        Скачивает HTML страницы и сохраняет в self.soup
        """
        resp = requests.get(url)
        resp.raise_for_status()
        self.soup = BeautifulSoup(resp.text, "html.parser")

    def parse(self, url: str) -> Dict[str, str]:
        """
        Парсит таблицу наблюдения с вертикальными заголовками
        и возвращает словарь:
        {
            "Time": "...",
            "Observer": "...",
            "Aurora colors": "...",
            ...
        }
        """
        self.__fetch_html(url)

        data = {}

        table = self.soup.find("table")
        if not table:
            return data

        for tr in table.find_all("tr"):
            th = tr.find("th")
            td = tr.find("td")

            if not th or not td:
                continue

            key = th.get_text(strip=True)
            value = td.get_text(strip=True)

            data[key] = value

        return data


if __name__ == "__main__":
    url = "https://www.spaceweatherlive.com/en/archive/2025/11/12/observations/25.html"

    parser = ObservationParser()
    obs = parser.parse(url)

    print(obs)
