import re
import os
import csv
from typing import Dict, Any, Optional
from datetime import datetime


class ObservationProcessor:
    def __init__(self, save_path = None):
        """
        obs — результат ObservationParser.parse(url)
        """
        self.save_path = save_path 
        self.obs = {}

    # ---------- базовые утилиты ----------

    @staticmethod
    def dms_to_decimal(dms_str: str) -> float:
        pattern = r'(\d+)°\s*(\d+)\'\s*(\d+)"\s*([NSEW])'
        match = re.match(pattern, dms_str.strip())

        if not match:
            raise ValueError(f"Неверный формат координаты: {dms_str}")

        deg, min_, sec, direction = match.groups()

        value = int(deg) + int(min_) / 60 + int(sec) / 3600
        if direction in ("S", "W"):
            value *= -1

        return value

    @staticmethod
    def duration_to_minutes(duration_str: str) -> Optional[int]:
        """
        '2 hours' -> 120
        '45 minutes' -> 45
        """
        if not duration_str:
            return None

        hours = re.search(r'(\d+)\s*hour', duration_str)
        minutes = re.search(r'(\d+)\s*minute', duration_str)

        total = 0
        if hours:
            total += int(hours.group(1)) * 60
        if minutes:
            total += int(minutes.group(1))

        return total if total > 0 else None

    @staticmethod
    def split_datetime(time_str: str):
        """
        'Wednesday, 12 November 2025 at 02:00 UTC'
        ->
        ('2025-11-12', '02:00:00')
        """
        dt = datetime.strptime(
            time_str,
            "%A, %d %B %Y at %H:%M UTC"
        )

        return dt.date().isoformat(), dt.time().isoformat(timespec="minutes")
    
    # ---------- универсальное разбиение forms и colors ----------
    @staticmethod
    def split_forms(s: str) -> str:
        """
        Разделяет формы, выделяя слова с заглавной буквы и блоки со скобками.
        ArcRaysStable Auroral Red arc (SAR) -> Arc;Rays;Stable Auroral Red arc (SAR)
        """
        pattern = r'^((?:[A-Z][a-z]*)+)(.*)$'
        match = re.match(pattern, s)
        
        if not match:
            return s
        
        camel_part = match.group(1)
        rest_of_string = match.group(2)
        
        words = re.findall(r'[A-Z][a-z]*', camel_part)
        
        result = ';'.join(words)
        
        if rest_of_string:
            rest_of_string = re.sub(r'(\))\s*([A-Z])', r'\1;\2', rest_of_string)
            result += rest_of_string
        
        return result

    @staticmethod
    def split_colors(s: str) -> str:
        """
        Разделяет слитные цвета: GreenRedPurple -> Green;Red;Purple
        """
        if not s:
            return ""
        matches = re.findall(r'[A-Z][a-z]*', s)
        return ";".join(matches)

    # ---------- основная обработка ----------

    def process(self, obs_raw: Dict[str, str]) -> Dict[str, Any]:
        obs = obs_raw.copy()
        self.obs = {}

        # Time -> date + time
        if "Time" in obs:
            date, time = self.split_datetime(obs["Time"])
            self.obs["date"] = date
            self.obs["time"] = time

        # Duration -> minutes
        if "Duration" in obs:
            self.obs["duration_min"] = self.duration_to_minutes(obs["Duration"])

        # Coordinates -> lat, lon
        if "Coordinates" in obs:
            lat_str, lon_str = obs["Coordinates"].split(" / ")
            self.obs["lat"] = self.dms_to_decimal(lat_str)
            self.obs["lon"] = self.dms_to_decimal(lon_str)

        # Переименование ключей и разделение
        if "Aurora forms" in obs:
            self.obs["forms"] = self.split_forms(obs["Aurora forms"])
        if "Aurora Colors" in obs:
            self.obs["colors"] = self.split_colors(obs["Aurora Colors"])

        # Удаляем ненужные ключи
        drop_keys = {
            "Observer", "Location", "Aurora visibility", "Aurora conditions",
            "Coordinates", "Time", "Duration",
            "Aurora brightness", "Aurora forms", "Aurora Colors"
        }
        for key in obs:
            if key not in drop_keys and key not in self.obs:
                self.obs[key] = obs[key]

        if self.save_path:
            self.to_csv()
        return self.obs

    # ---------- CSV ----------

    def to_csv(self):
        """
        Сохраняет результат в CSV.
        - Значения с несколькими элементами остаются как строки
        - Проверяем, есть ли файл, чтобы не писать заголовок повторно
        """
        if not self.save_path:
            raise ValueError("save_path не задан")

        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)

        file_exists = os.path.isfile(self.save_path)

        # Определяем порядок колонок
        fieldnames = [
            "date",
            "time",
            "duration_min",
            "lat",
            "lon",
            "forms",
            "colors"
        ]

        with open(self.save_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            # Пишем заголовок только если файла ещё нет
            if not file_exists:
                writer.writeheader()

            writer.writerow(self.obs)
