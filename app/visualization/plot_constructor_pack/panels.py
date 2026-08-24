from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Sequence

import pandas as pd

from app.visualization.plot_constructor_pack.models import (
    IONOSONDE_COLUMNS,
    TIME_COLUMN_CANDIDATES,
    ParsedPlot,
    PlotDescriptor,
    PlotPanel,
)
from app.visualization.plot_constructor_pack.registry import PlotRegistry


class PlotPanelBuilder:
    @staticmethod
    def chunked(values: Sequence[Any], chunk_size: int) -> list[list[Any]]:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive.")

        return [
            list(values[idx:idx + chunk_size])
            for idx in range(0, len(values), chunk_size)
        ]

    @staticmethod
    def prepare_map_time(plot_time: str | datetime, map_date: str | date | datetime | None = None) -> datetime:
        if isinstance(plot_time, str):
            value = plot_time.strip()
            if len(value) == 8 and value.count(":") == 2:
                if map_date is None:
                    raise ValueError("A map date is required when time is specified as HH:MM:SS.")
                date_value = map_date.strftime("%Y-%m-%d") if isinstance(map_date, (date, datetime)) else str(map_date)
                return datetime.strptime(f"{date_value} {value}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

        if isinstance(plot_time, datetime):
            return plot_time

        raise ValueError(f"Unsupported time value type: {type(plot_time)!r}")

    @classmethod
    def resolve_map_times(
        cls,
        data: dict[datetime, Any],
        params: dict[str, Any],
        descriptor: PlotDescriptor,
    ) -> list[datetime]:
        plot_times = params.get("time")
        map_date = params.get("date")

        if (
            params.get("plot_all_times")
            or params.get("all_times")
            or (
                isinstance(plot_times, str)
                and PlotRegistry.normalize_name(plot_times) in {"all", "available", "*"}
            )
        ):
            return sorted(data.keys())

        if plot_times is None:
            plot_times = [sorted(data.keys())[0]]

        if isinstance(plot_times, str):
            plot_times = [plot_times]

        prepared_times: list[datetime] = []

        for plot_time in plot_times:
            prepared_time = cls.prepare_map_time(plot_time, map_date=map_date)

            if prepared_time not in data:
                raise ValueError(
                    f"Time '{prepared_time}' is unavailable for map '{descriptor.name}'."
                )

            prepared_times.append(prepared_time)

        return prepared_times

    @staticmethod
    def resolve_cosmic_ray_stations(
        data: pd.DataFrame,
        params: dict[str, Any],
    ) -> list[str]:
        available_stations = [
            column
            for column in data.columns
            if column not in TIME_COLUMN_CANDIDATES
        ]
        requested_stations = params.get("stations")

        if requested_stations is None:
            return available_stations

        if isinstance(requested_stations, str):
            requested = [requested_stations]
        else:
            requested = list(requested_stations)

        missing = [station for station in requested if station not in available_stations]
        if missing:
            raise ValueError(f"Cosmic ray source is missing requested stations: {missing}")

        return requested
    
    @staticmethod
    def resolve_group_fields(params: dict[str, Any]) -> list[dict[str, Any]]:
        groups = params.get("groups") or []

        if not groups:
            fields = params.get("fields")
            if fields is None:
                return []

            return [
                {
                    "title": "OMNI",
                    "fields": fields,
                }
            ]

        return groups

    def expand(self, parsed: list[ParsedPlot]) -> list[PlotPanel]:
        panels: list[PlotPanel] = []

        for item in parsed:
            descriptor = item.descriptor
            params = item.params
            data = item.data
            column = item.column

            normalized_name = PlotRegistry.normalize_name(descriptor.name)

            if descriptor.plot_type == "map" and isinstance(data, dict) and data:
                prepared_times = self.resolve_map_times(
                    data=data,
                    params=params,
                    descriptor=descriptor,
                )

                ncols = int(params.get("ncols", 2))
                time_groups = self.chunked(prepared_times, ncols)

                for time_group in time_groups:
                    panels.append(
                        PlotPanel(
                            descriptor=descriptor,
                            params=params,
                            data=data,
                            column=column,
                            panel_name=descriptor.name,
                            map_times=tuple(time_group),
                        )
                    )

                continue

            if normalized_name == "ionosonde" and isinstance(data, pd.DataFrame):
                for ionosonde_column in IONOSONDE_COLUMNS:
                    if ionosonde_column not in data.columns:
                        raise ValueError(
                            f"Ionosonde source is missing required column: {ionosonde_column}"
                        )

                    panels.append(
                        PlotPanel(
                            descriptor=descriptor,
                            params=params,
                            data=data,
                            column=ionosonde_column,
                            panel_name=f"{descriptor.name}: {ionosonde_column}",
                        )
                    )

                continue

            if normalized_name in {"cosmic ray", "cosmic rays"} and isinstance(data, pd.DataFrame):
                layout = PlotRegistry.normalize_name(
                    str(params.get("station_layout", params.get("layout", "single")))
                )

                if layout not in {"single", "separate"}:
                    raise ValueError(
                        "Cosmic ray station layout must be 'single' or 'separate'."
                    )

                stations = self.resolve_cosmic_ray_stations(data, params)

                if layout == "separate":
                    for station in stations:
                        panels.append(
                            PlotPanel(
                                descriptor=descriptor,
                                params=params,
                                data=data,
                                column=station,
                                panel_name=f"{descriptor.name}: {station}",
                            )
                        )
                else:
                    panels.append(
                        PlotPanel(
                            descriptor=descriptor,
                            params=params,
                            data=data,
                            column=None,
                            panel_name=descriptor.name,
                        )
                    )

                continue

            if normalized_name == "omni" and isinstance(data, pd.DataFrame):
                groups = self.resolve_group_fields(params)

                if groups:
                    for group in groups:
                        title = group.get("title", descriptor.name)
                        fields = list(group.get("fields", []))

                        if not fields:
                            continue

                        panels.append(
                            PlotPanel(
                                descriptor=descriptor,
                                params={
                                    **params,
                                    "fields": fields,
                                },
                                data=data,
                                column=None,
                                panel_name=title,
                            )
                        )

                    continue

            panels.append(
                PlotPanel(
                    descriptor=descriptor,
                    params=params,
                    data=data,
                    column=column,
                    panel_name=descriptor.name,
                )
            )

        return panels
