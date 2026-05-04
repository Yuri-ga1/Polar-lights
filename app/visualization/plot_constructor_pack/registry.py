from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from app.visualization.plot_constructor_pack.models import (
    HIST_PLOT_NAMES,
    MAP_PLOT_NAMES,
    SOURCE_PLOT_NAMES,
    TIME_COLUMN_CANDIDATES,
    PlotDescriptor,
)


class PlotRegistry:
    def __init__(self, processor_results: Mapping[str, Any]) -> None:
        self.processor_results = dict(processor_results)
        self.registry = self._build_registry()

    @staticmethod
    def normalize_name(name: str) -> str:
        return " ".join(name.strip().lower().replace("_", " ").split())

    @classmethod
    def resolve_plot_type(cls, name: str, fallback: str = "timeseries") -> str:
        normalized = cls.normalize_name(name)

        if normalized in MAP_PLOT_NAMES:
            return "map"

        if normalized in HIST_PLOT_NAMES:
            return "histogram"

        return fallback

    @staticmethod
    def find_time_column(df: pd.DataFrame) -> str | None:
        for candidate in TIME_COLUMN_CANDIDATES:
            if candidate in df.columns:
                return candidate

        return None

    @staticmethod
    def is_map_dict(data: Any) -> bool:
        if not isinstance(data, dict) or not data:
            return False

        first_value = next(iter(data.values()))
        dtype_names = getattr(getattr(first_value, "dtype", None), "names", None)

        return bool(dtype_names and {"lat", "lon", "vals"}.issubset(set(dtype_names)))

    def _build_registry(self) -> dict[str, PlotDescriptor]:
        registry: dict[str, PlotDescriptor] = {}

        for source_key, data in self.processor_results.items():
            source_type = self.resolve_plot_type(source_key)
            normalized_source = self.normalize_name(source_key)

            if isinstance(data, pd.DataFrame):
                if normalized_source in SOURCE_PLOT_NAMES:
                    registry.setdefault(
                        normalized_source,
                        PlotDescriptor(
                            name=source_key,
                            plot_type=source_type,
                            source_key=source_key,
                        ),
                    )
                    continue

                if source_type == "map":
                    registry.setdefault(
                        normalized_source,
                        PlotDescriptor(
                            name=source_key,
                            plot_type="map",
                            source_key=source_key,
                        ),
                    )

                for column in data.columns:
                    if column in TIME_COLUMN_CANDIDATES:
                        continue

                    normalized_col = self.normalize_name(column)
                    plot_type = self.resolve_plot_type(column)

                    registry.setdefault(
                        normalized_col,
                        PlotDescriptor(
                            name=column,
                            plot_type=plot_type,
                            source_key=source_key,
                            column=column,
                        ),
                    )

            elif self.is_map_dict(data):
                registry.setdefault(
                    normalized_source,
                    PlotDescriptor(
                        name=source_key,
                        plot_type="map",
                        source_key=source_key,
                    ),
                )

            else:
                registry.setdefault(
                    normalized_source,
                    PlotDescriptor(
                        name=source_key,
                        plot_type=source_type,
                        source_key=source_key,
                    ),
                )

        return registry

    def descriptors(self) -> list[PlotDescriptor]:
        return sorted(self.registry.values(), key=lambda item: item.name)

    def available_plot_names(self) -> list[str]:
        return sorted(descriptor.name for descriptor in self.registry.values())

    def resolve_descriptor(self, requested_name: str) -> PlotDescriptor:
        key = self.normalize_name(requested_name)
        descriptor = self.registry.get(key)

        if descriptor is None:
            available = ", ".join(self.available_plot_names())
            raise ValueError(f"Unknown plot '{requested_name}'. Available plots: {available}")

        return descriptor

    def extract_plot_data(self, descriptor: PlotDescriptor) -> tuple[Any, str | None]:
        if descriptor.source_key not in self.processor_results:
            raise ValueError(
                f"Missing data source '{descriptor.source_key}' for plot '{descriptor.name}'."
            )

        data = self.processor_results[descriptor.source_key]
        if data is None:
            raise ValueError(
                f"Data for plot '{descriptor.name}' is missing "
                f"(source '{descriptor.source_key}' is None)."
            )

        if isinstance(data, pd.DataFrame) and descriptor.column is not None:
            if descriptor.column not in data.columns:
                raise ValueError(
                    f"Column '{descriptor.column}' required by '{descriptor.name}' "
                    f"is absent in source '{descriptor.source_key}'."
                )

            return data, descriptor.column

        return data, None