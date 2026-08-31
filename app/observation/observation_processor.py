from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional


class ObservationProcessor:
    """Convert SpaceWeatherLive table fields to the shared CSV schema."""

    def __init__(self, save_path: str | None = None):
        self.save_path = save_path

    @staticmethod
    def dms_to_decimal(value: str) -> float:
        match = re.match(r'(\d+)°\s*(\d+)\'\s*(\d+)"\s*([NSEW])', value.strip())
        if not match:
            raise ValueError(f"Invalid coordinate: {value}")
        degrees, minutes, seconds, direction = match.groups()
        result = int(degrees) + int(minutes) / 60 + int(seconds) / 3600
        return -result if direction in ("S", "W") else result

    @staticmethod
    def duration_to_minutes(value: str) -> Optional[int]:
        if not value:
            return None
        hours = re.search(r'(\d+)\s*hour', value)
        minutes = re.search(r'(\d+)\s*minute', value)
        total = (int(hours.group(1)) * 60 if hours else 0) + (int(minutes.group(1)) if minutes else 0)
        return total or None

    @staticmethod
    def split_datetime(value: str) -> tuple[str, str]:
        dt = datetime.strptime(value, "%A, %d %B %Y at %H:%M UTC")
        return dt.date().isoformat(), dt.time().isoformat(timespec="seconds")

    @staticmethod
    def split_colors(value: str) -> str:
        return ";".join(re.findall(r'[A-Z][a-z]*', value or ""))

    @staticmethod
    def split_forms(value: str) -> str:
        if not value:
            return ""
        parts = re.findall(r'[A-Z][a-z]*(?:\s+[a-z]+)*', value)
        return ";".join(part.strip() for part in parts if part.strip())

    def process(self, raw: Dict[str, str]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if raw.get("Time"):
            result["date"], result["time"] = self.split_datetime(raw["Time"])
        if raw.get("Duration") is not None:
            result["duration_min"] = self.duration_to_minutes(raw.get("Duration", ""))
        if raw.get("Coordinates"):
            latitude, longitude = raw["Coordinates"].split(" / ")
            result["lat"] = self.dms_to_decimal(latitude)
            result["lon"] = self.dms_to_decimal(longitude)
        result["forms"] = self.split_forms(raw.get("Aurora forms", ""))
        result["colors"] = self.split_colors(raw.get("Aurora Colors", ""))
        if self.save_path:
            self.to_csv(result)
        return result

    def to_csv(self, observation: Dict[str, Any]) -> None:
        if not self.save_path:
            raise ValueError("save_path is not set")
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
        fields = ["date", "time", "duration_min", "lat", "lon", "forms", "colors"]
        exists = os.path.isfile(self.save_path)
        with open(self.save_path, "a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            if not exists:
                writer.writeheader()
            writer.writerow(observation)
