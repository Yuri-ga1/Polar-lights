from __future__ import annotations

from abc import ABC
from datetime import date, datetime
from pathlib import Path
from typing import Union


class BaseProcessor(ABC):
    """Базовый класс для всех `*Processor` с общими утилитами."""

    def __init__(self, folder_path: str | Path | None = None) -> None:
        self.folder_path: Path | None = Path(folder_path) if folder_path is not None else None

    @staticmethod
    def _parse_date(value: str) -> date:
        return datetime.strptime(value, "%Y-%m-%d").date()

    @staticmethod
    def _coerce_date(value: Union[str, date, datetime]) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return BaseProcessor._parse_date(value)

    def _full_path(self, filename: str) -> str:
        if self.folder_path is None:
            raise ValueError("folder_path не задан")
        return str(self.folder_path / filename)

    @staticmethod
    def _is_non_empty_file(path: str | Path | None) -> bool:
        if path is None:
            return False
        candidate = Path(path)
        return candidate.exists() and candidate.stat().st_size > 0
