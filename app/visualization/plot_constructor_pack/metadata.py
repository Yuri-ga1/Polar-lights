from __future__ import annotations

from typing import Any

import pandas as pd

from app.visualization.plot_constructor_pack.models import (
    IONOSONDE_COLUMNS,
    TIME_COLUMN_CANDIDATES,
    PlotDescriptor,
)
from app.visualization.plot_constructor_pack.registry import PlotRegistry


class PlotMetadataBuilder:
    def __init__(self, processor_results: dict[str, Any], registry: PlotRegistry) -> None:
        self.processor_results = processor_results
        self.registry = registry

    def available_plots(self, with_details: bool = True) -> list[str | dict[str, Any]]:
        if not with_details:
            return self.registry.available_plot_names()

        return [
            self._build_plot_info(descriptor)
            for descriptor in self.registry.descriptors()
        ]

    def _build_plot_info(self, descriptor: PlotDescriptor) -> str | dict[str, Any]:
        data = self.processor_results.get(descriptor.source_key)

        if isinstance(data, dict) and data:
            times = sorted(data.keys())

            info: dict[str, Any] = {
                descriptor.name: {
                    "type": descriptor.plot_type,
                    "time_start": str(times[0]),
                    "time_end": str(times[-1]),
                }
            }

            if len(times) > 1:
                info[descriptor.name]["time_step"] = str(times[1] - times[0])

            return info

        if isinstance(data, pd.DataFrame):
            normalized_name = PlotRegistry.normalize_name(descriptor.name)

            if normalized_name in {"cosmic ray", "cosmic rays"}:
                stations = [
                    column
                    for column in data.columns
                    if column not in TIME_COLUMN_CANDIDATES
                ]

                return {
                    descriptor.name: {
                        "type": descriptor.plot_type,
                        "stations": stations,
                    }
                }

            if normalized_name == "ionosonde":
                return {
                    descriptor.name: {
                        "type": descriptor.plot_type,
                        "parameters": list(IONOSONDE_COLUMNS),
                    }
                }

            time_col = self.registry.find_time_column(data)
            if time_col is not None and not data.empty:
                time_values = pd.to_datetime(data[time_col], errors="coerce").dropna()

                if not time_values.empty:
                    return {
                        descriptor.name: {
                            "type": descriptor.plot_type,
                            "time_start": str(time_values.min()),
                            "time_end": str(time_values.max()),
                        }
                    }

        return descriptor.name