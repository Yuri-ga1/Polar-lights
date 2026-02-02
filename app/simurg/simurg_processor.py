from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Union

import h5py
from numpy.typing import NDArray

TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


class SimurgProcessor:
    """
    Локальный процессор SIMuRG HDF5-файлов.

    Возвращает:
    - dict[datetime, NDArray], если файл найден и содержит данные
    - None, если файла нет / он пустой / не удалось распарсить
    """

    def __init__(self, folder_path: str | Path) -> None:
        self.folder_path = Path(folder_path)

    @staticmethod
    def _normalize_time(value: datetime) -> datetime:
        return value.replace(tzinfo=value.tzinfo or timezone.utc)

    @classmethod
    def _parse_time(cls, value: str) -> datetime:
        parsed = datetime.strptime(value, TIME_FORMAT)
        return cls._normalize_time(parsed)

    @staticmethod
    def _coerce_date(value: Union[str, date, datetime]) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return datetime.strptime(value, "%Y-%m-%d").date()

    def _find_file(self, target_date: date) -> Optional[Path]:
        if not self.folder_path.exists():
            return None
        year = target_date.year
        doy = target_date.timetuple().tm_yday
        prefix = f"roti_{year}_{doy:03d}_-90_90_N_-180_180_E_"
        matches = sorted(self.folder_path.glob(f"{prefix}*.h5"))
        return matches[0] if matches else None

    def load(self, date_value: Union[str, date, datetime]) -> Optional[Dict[datetime, NDArray]]:
        target_date = self._coerce_date(date_value)
        file_path = self._find_file(target_date)
        if not file_path or not file_path.exists() or file_path.stat().st_size == 0:
            return None

        data: Dict[datetime, NDArray] = {}

        try:
            with h5py.File(file_path, "r") as handle:
                if "data" not in handle:
                    return None
                for str_time in list(handle["data"]):
                    parsed_time = self._parse_time(str_time)
                    data[parsed_time] = handle["data"][str_time][:]
        except Exception:
            return None

        return data or None
