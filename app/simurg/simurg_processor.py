from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from enum import Enum
from collections.abc import Iterator
from typing import Dict, Optional, Union

import h5py
from numpy.typing import NDArray
from app.base_classes.base_processor import BaseProcessor

TIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

class SimurgData(dict):
    """SIMuRG data dictionary with source-file time metadata."""

    def __init__(
        self,
        *args,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
        time_step: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.time_start = time_start
        self.time_end = time_end
        self.time_step = time_step

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
        
    @classmethod
    def _format_time_key(cls, value: str | datetime) -> str:
        if isinstance(value, str):
            value = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")

        value = cls._normalize_time(value)

        return value.strftime(TIME_FORMAT)
    
    @classmethod
    def _resolve_time_keys(
        cls,
        data_group,
        times: list[str | datetime],
    ) -> list[str]:
        available_keys = set(data_group.keys())
        selected_keys: list[str] = []

        for value in times:
            requested_key = cls._format_time_key(value)

            if requested_key in available_keys:
                selected_keys.append(requested_key)
                continue

            requested_dt = cls._normalize_time(
                datetime.strptime(
                    requested_key,
                    TIME_FORMAT,
                )
            )

            nearest_key = min(
                available_keys,
                key=lambda key: abs(cls._parse_time(key) - requested_dt),
            )

            selected_keys.append(nearest_key)

        return selected_keys
    
    @classmethod
    def _build_time_metadata(cls, time_keys: list[str]) -> dict[str, object]:
        if not time_keys:
            return {
                "time_start": None,
                "time_end": None,
                "time_step": None,
            }

        parsed_times = sorted(cls._parse_time(key) for key in time_keys)

        time_step = None
        if len(parsed_times) > 1:
            steps = [
                parsed_times[idx + 1] - parsed_times[idx]
                for idx in range(len(parsed_times) - 1)
            ]

            most_common_step = max(set(steps), key=steps.count)
            time_step = str(most_common_step)

        return {
            "time_start": parsed_times[0],
            "time_end": parsed_times[-1],
            "time_step": time_step,
        }

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
        times: Optional[list[str | datetime]] = None,
    ) -> Optional[Dict[datetime, NDArray]]:
        target_date = self._coerce_date(date_value)
        normalized_product = self._normalize_product(product_type)
        file_path = self._find_file(target_date, normalized_product)

        if not self._is_non_empty_file(file_path):
            return None

        data: SimurgData = SimurgData()
        time_metadata: dict[str, object] = {}

        try:
            with h5py.File(file_path, "r") as handle:
                if "data" not in handle:
                    return None

                data_group = handle["data"]
                time_metadata = self._build_time_metadata(list(data_group.keys()))

                if times is None:
                    selected_keys = list(data_group.keys())
                else:
                    selected_keys = self._resolve_time_keys(
                        data_group=data_group,
                        times=times,
                    )

                for str_time in selected_keys:
                    parsed_time = self._parse_time(str_time)
                    data[parsed_time] = data_group[str_time][:]

        except Exception:
            return None

        if not data:
            return None

        return SimurgData(
            data,
            time_start=time_metadata.get("time_start"),
            time_end=time_metadata.get("time_end"),
            time_step=time_metadata.get("time_step"),
        )

    def available_times(
        self,
        date_value: Union[str, date, datetime],
        product_type: str | DataProduct = DataProduct.ROTI,
    ) -> list[datetime]:
        target_date = self._coerce_date(date_value)
        normalized_product = self._normalize_product(product_type)
        file_path = self._find_file(target_date, normalized_product)

        if not self._is_non_empty_file(file_path):
            return []

        try:
            with h5py.File(file_path, "r") as handle:
                if "data" not in handle:
                    return []

                return sorted(self._parse_time(key) for key in handle["data"].keys())
        except Exception:
            return []

    def iter_slices(
        self,
        date_value: Union[str, date, datetime],
        product_type: str | DataProduct = DataProduct.ROTI,
        times: Optional[list[str | datetime]] = None,
    ) -> Iterator[tuple[datetime, NDArray]]:
        target_date = self._coerce_date(date_value)
        normalized_product = self._normalize_product(product_type)
        file_path = self._find_file(target_date, normalized_product)

        if not self._is_non_empty_file(file_path):
            return

        try:
            with h5py.File(file_path, "r") as handle:
                if "data" not in handle:
                    return

                data_group = handle["data"]

                if times is None:
                    selected_keys = list(data_group.keys())
                else:
                    selected_keys = self._resolve_time_keys(
                        data_group=data_group,
                        times=times,
                    )

                for str_time in selected_keys:
                    yield self._parse_time(str_time), data_group[str_time][:]

        except Exception:
            return
