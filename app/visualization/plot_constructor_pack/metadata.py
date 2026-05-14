from __future__ import annotations

from typing import Any

import pandas as pd

from app.visualization.plot_constructor_pack.models import (
    IONOSONDE_COLUMNS,
    SERVICE_COLUMNS,
    PlotDescriptor,
)
from app.visualization.plot_constructor_pack.registry import PlotRegistry


class PlotMetadataBuilder:
    def __init__(self, processor_results: dict[str, Any], registry: PlotRegistry) -> None:
        self.processor_results = processor_results
        self.registry = registry

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, list):
            if not value:
                return "none"

            return ", ".join(str(item) for item in value)

        return str(value)
    
    @staticmethod
    def _is_service_column(column: str) -> bool:
        normalized_column = str(column).strip().lower()
        normalized_service_columns = {
            str(service_column).strip().lower()
            for service_column in SERVICE_COLUMNS
        }

        return normalized_column in normalized_service_columns

    def available_plots_markdown(self) -> str:
        plot_infos = self.available_plots(with_details=True)

        lines: list[str] = ["## Available plots", ""]

        for item in plot_infos:
            if isinstance(item, str):
                lines.extend(
                    [
                        f"### {item}",
                        "",
                        "- No additional metadata available.",
                        "",
                    ]
                )
                continue

            for plot_name, details in item.items():
                lines.extend([f"### {plot_name}", ""])

                if not isinstance(details, dict):
                    lines.extend([f"- {details}", ""])
                    continue

                for key, value in details.items():
                    formatted_value = self._format_value(value)
                    lines.append(f"- **{key}**: {formatted_value}")

                lines.append("")

        return "\n".join(lines)

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
            selected_times = sorted(data.keys())

            time_start = getattr(data, "time_start", selected_times[0])
            time_end = getattr(data, "time_end", selected_times[-1])
            time_step = getattr(data, "time_step", None)

            info: dict[str, Any] = {
                descriptor.name: {
                    "type": descriptor.plot_type,
                    "time_start": str(time_start),
                    "time_end": str(time_end),
                    "time_step": str(time_step),
                    "selected_times": [str(time) for time in selected_times],
                }
            }

            return info

        if isinstance(data, pd.DataFrame):
            normalized_name = PlotRegistry.normalize_name(descriptor.name)

            if normalized_name == "omni":
                fields = [
                    column
                    for column in data.columns
                    if not self._is_service_column(column)
                ]

                time_col = self.registry.find_time_column(data)

                info = {
                    descriptor.name: {
                        "type": descriptor.plot_type,
                        "fields": fields,
                    }
                }

                if time_col is not None and not data.empty:
                    time_values = pd.to_datetime(data[time_col], errors="coerce").dropna()

                    if not time_values.empty:
                        info[descriptor.name]["time_start"] = str(time_values.min())
                        info[descriptor.name]["time_end"] = str(time_values.max())

                return info

            if normalized_name in {"cosmic ray", "cosmic rays"}:
                stations = [
                    column
                    for column in data.columns
                    if not self._is_service_column(column)
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