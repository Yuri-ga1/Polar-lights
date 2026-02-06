from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from enum import Enum
from typing import Dict, Optional, Union

import h5py
from numpy.typing import NDArray
from app.base_classes.base_processor import BaseProcessor

TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

class DataProduct(str, Enum):
    ROTI = "roti"
    TEC_ADJUSTED = "tec_adjusted"

class SimurgProcessor(BaseProcessor):
    """
    Локальный процессор SIMuRG HDF5-файлов.

    Возвращает:
    - dict[datetime, NDArray], если файл найден и содержит данные
    - None, если файла нет / он пустой / не удалось распарсить
    """

    def __init__(self, folder_path: str | Path) -> None:
        super().__init__(folder_path)

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

    @classmethod
    def _normalize_product(cls, product_type: str | "DataProduct") -> "DataProduct":
        if isinstance(product_type, DataProduct):
            return product_type
        try:
            return DataProduct(product_type)
        except ValueError as error:
            supported = ", ".join(p.value for p in DataProduct)
            raise ValueError(f"Неизвестный тип продукта: {product_type}. Поддерживаются: {supported}") from error

    def _find_file(
        self,
        target_date: date,
        product_type: DataProduct,
    ) -> Optional[Path]:
        if not self.folder_path.exists():
            return None
        year = target_date.year
        doy = target_date.timetuple().tm_yday
        prefix = f"{product_type.value}_{year}_{doy:03d}_-90_90_N_-180_180_E_"
        matches = sorted(self.folder_path.glob(f"{prefix}*.h5"))
        return matches[0] if matches else None

    def load(
        self,
        date_value: Union[str, date, datetime],
        product_type: str | DataProduct = DataProduct.ROTI,
    ) -> Optional[Dict[datetime, NDArray]]:
        
        target_date = self._coerce_date(date_value)
        normalized_product = self._normalize_product(product_type)
        file_path = self._find_file(target_date, normalized_product)

        if not self._is_non_empty_file(file_path):
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
