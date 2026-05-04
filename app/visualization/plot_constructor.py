from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from math import ceil
from matplotlib.gridspec import GridSpecFromSubplotSpec

import cartopy.crs as ccrs
from app.visualization.plot_utils import (
    plot_histogram_on_ax,
    plot_kp_bars,
    plot_timeseries_on_ax,
)
from app.visualization.roti_plotter import plot_simurg_map_on_ax
from app.visualization.gim_plotter import plot_gim_map_on_ax
from app.visualization.aurora_map_plotter import plot_aurora_observations_on_ax


MAP_PLOT_NAMES = {
    "roti",
    "gim",
    "adjusted tec",
    "tec adjusted",
    "keogram",
    "aurora observation",
    "aurora",
}
HIST_PLOT_NAMES = {"kp"}
SOURCE_PLOT_NAMES = {"ionosonde", "cosmic ray", "cosmic rays"}
TIME_COLUMN_CANDIDATES = ("datetime", "DateTime", "time", "timestamp")
IONOSONDE_COLUMNS = ("dfoF2", "dhmF2")


@dataclass(frozen=True)
class PlotDescriptor:
    """Description of one available plot and how to read its data from processor results."""

    name: str
    plot_type: str
    source_key: str
    column: str | None = None


class PlotConstructor:
    """Build stacked plots from processor outputs using plot names.

    Parameters
    ----------
    processor_results:
        Mapping of source name -> processor output. Typical values are pandas DataFrame,
        dict[datetime, numpy.ndarray] map-like products, or other series-like containers.
    """

    def __init__(self, processor_results: Mapping[str, Any]) -> None:
        self.processor_results = dict(processor_results)
        self._registry = self._build_registry()

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.strip().lower().replace("_", " ").split())

    @classmethod
    def _resolve_plot_type(cls, name: str, fallback: str = "timeseries") -> str:
        normalized = cls._normalize_name(name)
        if normalized in MAP_PLOT_NAMES:
            return "map"
        if normalized in HIST_PLOT_NAMES:
            return "histogram"
        return fallback

    @staticmethod
    def _find_time_column(df: pd.DataFrame) -> str | None:
        for candidate in TIME_COLUMN_CANDIDATES:
            if candidate in df.columns:
                return candidate
        return None

    @staticmethod
    def _is_map_dict(data: Any) -> bool:
        if not isinstance(data, dict) or not data:
            return False
        first_value = next(iter(data.values()))
        dtype_names = getattr(getattr(first_value, "dtype", None), "names", None)
        return bool(dtype_names and {"lat", "lon", "vals"}.issubset(set(dtype_names)))
    
    @staticmethod
    def _resolve_x_range(params: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        left = params.get("date_start") or params.get("x_start")
        right = params.get("date_end") or params.get("x_end")

        if left is None or right is None:
            return None

        x_start = pd.to_datetime(left, errors="coerce")
        x_end = pd.to_datetime(right, errors="coerce")

        if pd.isna(x_start) or pd.isna(x_end):
            raise ValueError("Invalid x-axis range. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS for date_start/date_end.")

        if x_end < x_start:
            raise ValueError("x-axis range is invalid: date_end must be greater than or equal to date_start.")

        return pd.Timestamp(x_start), pd.Timestamp(x_end)

    @classmethod
    def _apply_x_range(cls, ax: plt.Axes, params: dict[str, Any]) -> None:
        x_range = cls._resolve_x_range(params)
        if x_range is None:
            return
        x_start, x_end = x_range
        ax.set_xlim(x_start.to_pydatetime(), x_end.to_pydatetime())

    def _build_registry(self) -> dict[str, PlotDescriptor]:
        registry: dict[str, PlotDescriptor] = {}

        for source_key, data in self.processor_results.items():
            source_type = self._resolve_plot_type(source_key)
            normalized_source = self._normalize_name(source_key)

            if isinstance(data, pd.DataFrame):
                # Register explicit source-level plots that should be requested as one plot,
                # instead of being available only through their individual DataFrame columns.
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

                # Register source name itself for map-like aurora observations in tabular form.
                if source_type == "map":
                    registry.setdefault(
                        normalized_source,
                        PlotDescriptor(name=source_key, plot_type="map", source_key=source_key),
                    )

                for column in data.columns:
                    if column in TIME_COLUMN_CANDIDATES:
                        continue
                    normalized_col = self._normalize_name(column)
                    plot_type = self._resolve_plot_type(column)
                    registry.setdefault(
                        normalized_col,
                        PlotDescriptor(
                            name=column,
                            plot_type=plot_type,
                            source_key=source_key,
                            column=column,
                        ),
                    )
            elif self._is_map_dict(data):
                registry.setdefault(
                    normalized_source,
                    PlotDescriptor(name=source_key, plot_type="map", source_key=source_key),
                )
            else:
                registry.setdefault(
                    normalized_source,
                    PlotDescriptor(name=source_key, plot_type=source_type, source_key=source_key),
                )

        return registry

    def available_plots(self) -> list[str]:
        """Return sorted list of plot names available for the provided processor results."""
        return sorted(descriptor.name for descriptor in self._registry.values())

    def _resolve_descriptor(self, requested_name: str) -> PlotDescriptor:
        key = self._normalize_name(requested_name)
        descriptor = self._registry.get(key)
        if descriptor is None:
            available = ", ".join(self.available_plots())
            raise ValueError(f"Unknown plot '{requested_name}'. Available plots: {available}")
        return descriptor

    def _extract_plot_data(self, descriptor: PlotDescriptor) -> tuple[Any, str | None]:
        if descriptor.source_key not in self.processor_results:
            raise ValueError(
                f"Missing data source '{descriptor.source_key}' for plot '{descriptor.name}'."
            )

        data = self.processor_results[descriptor.source_key]
        if data is None:
            raise ValueError(
                f"Data for plot '{descriptor.name}' is missing (source '{descriptor.source_key}' is None)."
            )

        if isinstance(data, pd.DataFrame) and descriptor.column is not None:
            if descriptor.column not in data.columns:
                raise ValueError(
                    f"Column '{descriptor.column}' required by '{descriptor.name}' is absent in source '{descriptor.source_key}'."
                )
            return data, descriptor.column

        return data, None
    
    def _collect_map_time_markers(
        self,
        parsed: list[tuple[PlotDescriptor, dict[str, Any], Any, str | None]],
    ) -> list[pd.Timestamp]:
        markers: list[pd.Timestamp] = []

        for descriptor, params, _, _ in parsed:
            if descriptor.plot_type != "map":
                continue

            markers.extend(self._parse_time_markers(params.get("time")))

        return markers
    
    def _add_map_axis(
        self,
        fig: plt.Figure,
        inner_grid: GridSpecFromSubplotSpec,
        map_idx: int,
        maps_count: int,
        ncols: int,
    ) -> plt.Axes:
        is_last = map_idx == maps_count - 1
        is_odd = maps_count % 2 == 1

        row = map_idx // ncols
        col = map_idx % ncols

        if is_last and is_odd and ncols > 1:
            return fig.add_subplot(
                inner_grid[row, :],
                projection=ccrs.PlateCarree(),
            )

        return fig.add_subplot(
            inner_grid[row, col],
            projection=ccrs.PlateCarree(),
        )

    def _plot_map(self, ax: plt.Axes, descriptor: PlotDescriptor, data: Any, params: dict[str, Any]) -> None:
        normalized_name = self._normalize_name(descriptor.name)

        if isinstance(data, dict) and data:
            plot_times = params.get("time")
            for plot_time_str in plot_times:
                plot_time = datetime.strptime(plot_time_str, '%Y-%m-%d %H:%M:%S')
                plot_time = plot_time.replace(tzinfo=timezone.utc)
                if plot_time is None:
                    plot_time = sorted(data.keys())[0]
                if plot_time not in data:
                    raise ValueError(f"Time '{plot_time}' is unavailable for map '{descriptor.name}'.")
                arr = data[plot_time]

                if normalized_name == "gim":
                    plot_gim_map_on_ax(
                        ax,
                        arr,
                        title=f"{descriptor.name} ({plot_time})",
                        cmap=params.get("cmap", "jet"),
                    )
                else:
                    limits = (0.0, 80.0) if normalized_name in {"adjusted tec", "tec adjusted"} else (0.0, 1.0)
                    plot_simurg_map_on_ax(
                        ax,
                        arr,
                        title=f"{descriptor.name} ({plot_time})",
                        cmap=params.get("cmap", "jet"),
                        point_size=params.get("s", 8),
                        colorbar_limits=limits,
                    )
            return

        if isinstance(data, pd.DataFrame):
            if normalized_name in {"aurora observation", "aurora"}:
                time_value = params.get("time")
                if time_value is None:
                    date_col = pd.to_datetime(data.get("date"), errors="coerce").dropna()
                    if date_col.empty:
                        raise ValueError(
                            f"Map plot '{descriptor.name}' requires a valid 'date' column for aurora observations."
                        )
                    time_value = pd.Timestamp(date_col.iloc[0]).to_pydatetime()
                plot_aurora_observations_on_ax(
                    ax,
                    data,
                    time=time_value,
                    show_geomagnetic_equator=params.get("show_geomagnetic_equator", True),
                    show_terminator=params.get("show_terminator", True),
                    point_radius=params.get("point_radius", 1.0),
                )
                ax.set_title(descriptor.name)
                return

            if not {"lat", "lon"}.issubset(set(data.columns)):
                raise ValueError(
                    f"Map plot '{descriptor.name}' requires 'lat' and 'lon' columns in source '{descriptor.source_key}'."
                )
            # fallback for other map-like tabular data: via existing SIMuRG-like renderer is not applicable
            raise ValueError(
                f"Map plot '{descriptor.name}' expects processor data in map dictionary format or aurora-observation table."
            )
            return

        raise ValueError(f"Unsupported map data format for plot '{descriptor.name}'.")

    def _plot_histogram(
        self,
        ax: plt.Axes,
        descriptor: PlotDescriptor,
        data: Any,
        column: str | None,
        params: dict[str, Any],
    ) -> None:
        if isinstance(data, pd.DataFrame):
            series = data[column] if column else data.iloc[:, 0]
        else:
            series = pd.Series(data)

        if self._normalize_name(descriptor.name) == "kp":
            if isinstance(data, pd.DataFrame):
                plot_kp_bars(ax=ax, kp_df=data, set_xlabel=False)
                ax.set_title(descriptor.name)
                return

        plot_histogram_on_ax(
            ax,
            series,
            bins=params.get("bins", 9),
            color=params.get("color", "tab:green"),
            title=descriptor.name,
        )
        self._apply_x_range(ax, params)


    @staticmethod
    def _parse_time_markers(raw_time: Any) -> list[pd.Timestamp]:
        if raw_time is None:
            return []
        values = raw_time if isinstance(raw_time, (list, tuple, set)) else [raw_time]
        markers: list[pd.Timestamp] = []
        for value in values:
            ts = pd.to_datetime(value, errors="coerce", utc=True)
            if pd.isna(ts):
                continue
            markers.append(pd.Timestamp(ts))
        return markers

    def _plot_timeseries(
        self,
        ax: plt.Axes,
        descriptor: PlotDescriptor,
        data: Any,
        column: str | None,
        params: dict[str, Any],
    ) -> None:
        if isinstance(data, pd.DataFrame):
            time_col = self._find_time_column(data)

            if time_col is None:
                raise ValueError(
                    f"Timeseries '{descriptor.name}' needs one of {TIME_COLUMN_CANDIDATES}, "
                    f"but none found in '{descriptor.source_key}'."
                )

            y_col = column or next((c for c in data.columns if c != time_col), None)

            if y_col is None:
                raise ValueError(f"No value column found for timeseries '{descriptor.name}'.")

            plot_timeseries_on_ax(
                ax,
                data,
                time_col=time_col,
                value_col=y_col,
                color=params.get("color", "tab:blue"),
                linewidth=params.get("linewidth", 1.5),
                title=descriptor.name,
                ylabel=y_col,
            )
            self._apply_x_range(ax, params)

            for marker in params.get("time_markers", []):
                marker_local = marker.tz_convert(None) if marker.tzinfo is not None else marker

                ax.axvline(
                    marker_local,
                    color=params.get("time_marker_color", "tab:red"),
                    linestyle=params.get("time_marker_linestyle", "--"),
                    linewidth=params.get("time_marker_linewidth", 1.2),
                    alpha=params.get("time_marker_alpha", 0.8),
                )

            return

        if isinstance(data, (Sequence, np.ndarray)) and not isinstance(data, (str, bytes)):
            ax.plot(data, color=params.get("color", "tab:blue"))
            ax.set_title(descriptor.name)
            ax.grid(True, alpha=0.3)
            return

        raise ValueError(f"Unsupported timeseries data format for plot '{descriptor.name}'.")

    def _plot_ionosonde_source(
        self,
        fig: plt.Figure,
        subplot_spec,
        descriptor: PlotDescriptor,
        data: pd.DataFrame,
        params: dict[str, Any],
    ) -> list[plt.Axes]:
        missing = [column for column in IONOSONDE_COLUMNS if column not in data.columns]
        if missing:
            raise ValueError(f"Ionosonde source is missing required columns: {missing}")

        inner_grid = GridSpecFromSubplotSpec(
            len(IONOSONDE_COLUMNS),
            1,
            subplot_spec=subplot_spec,
            hspace=0.25,
        )

        axes: list[plt.Axes] = []
        for idx, column in enumerate(IONOSONDE_COLUMNS):
            ax = fig.add_subplot(inner_grid[idx, 0])
            column_params = dict(params)
            column_params.setdefault("linewidth", params.get("linewidth", 1.5))
            self._plot_timeseries(
                ax=ax,
                descriptor=PlotDescriptor(
                    name=column,
                    plot_type="timeseries",
                    source_key=descriptor.source_key,
                    column=column,
                ),
                data=data,
                column=column,
                params=column_params,
            )
            ax.set_title(f"{descriptor.name}: {column}")
            axes.append(ax)

        return axes

    @staticmethod
    def _resolve_cosmic_ray_stations(data: pd.DataFrame, params: dict[str, Any]) -> list[str]:
        available_stations = [column for column in data.columns if column not in TIME_COLUMN_CANDIDATES]
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

    def _plot_cosmic_ray_source(
        self,
        fig: plt.Figure,
        subplot_spec,
        descriptor: PlotDescriptor,
        data: pd.DataFrame,
        params: dict[str, Any],
    ) -> list[plt.Axes]:
        stations = self._resolve_cosmic_ray_stations(data, params)
        if not stations:
            raise ValueError("Cosmic ray source has no station columns to plot.")

        layout = self._normalize_name(str(params.get("station_layout", params.get("layout", "single"))))
        if layout not in {"single", "separate"}:
            raise ValueError("Cosmic ray station layout must be 'single' or 'separate'.")

        if layout == "single":
            ax = fig.add_subplot(subplot_spec)
            time_col = self._find_time_column(data)
            if time_col is None:
                raise ValueError(
                    f"Timeseries '{descriptor.name}' needs one of {TIME_COLUMN_CANDIDATES}, "
                    f"but none found in '{descriptor.source_key}'."
                )

            for station in stations:
                ax.plot(
                    data[time_col],
                    data[station],
                    linewidth=params.get("linewidth", 1.5),
                    label=station,
                )

            ax.set_title(descriptor.name)
            ax.set_ylabel(params.get("ylabel", "%"))
            ax.grid(True, alpha=0.3)
            ax.legend()
            self._apply_x_range(ax, params)
            return [ax]

        inner_grid = GridSpecFromSubplotSpec(
            len(stations),
            1,
            subplot_spec=subplot_spec,
            hspace=0.25,
        )

        axes: list[plt.Axes] = []
        for idx, station in enumerate(stations):
            ax = fig.add_subplot(inner_grid[idx, 0])
            self._plot_timeseries(
                ax=ax,
                descriptor=PlotDescriptor(
                    name=station,
                    plot_type="timeseries",
                    source_key=descriptor.source_key,
                    column=station,
                ),
                data=data,
                column=station,
                params=params,
            )
            ax.set_title(f"{descriptor.name}: {station}")
            axes.append(ax)

        return axes

    def _plot_source_timeseries(
        self,
        fig: plt.Figure,
        subplot_spec,
        descriptor: PlotDescriptor,
        data: Any,
        params: dict[str, Any],
    ) -> list[plt.Axes] | None:
        normalized_name = self._normalize_name(descriptor.name)
        if not isinstance(data, pd.DataFrame):
            return None

        if normalized_name == "ionosonde":
            return self._plot_ionosonde_source(fig, subplot_spec, descriptor, data, params)

        if normalized_name in {"cosmic ray", "cosmic rays"}:
            return self._plot_cosmic_ray_source(fig, subplot_spec, descriptor, data, params)

        return None

    def plot(
        self,
        plots: Sequence[str | Mapping[str, Any]],
        *,
        figsize: tuple[float, float] | None = None,
    ) -> tuple[plt.Figure, list[plt.Axes]]:
        """Plot requested charts vertically in the same order as input list."""
        if not plots:
            raise ValueError("plots list is empty.")

        parsed: list[tuple[PlotDescriptor, dict[str, Any], Any, str | None]] = []

        for item in plots:
            if isinstance(item, str):
                name = item
                params: dict[str, Any] = {}
            elif isinstance(item, Mapping):
                name = str(item.get("name", "")).strip()
                params = dict(item.get("params", {}))
            else:
                raise ValueError(f"Unsupported plot spec type: {type(item)!r}")

            if not name:
                raise ValueError("Each plot spec must contain non-empty 'name'.")

            descriptor = self._resolve_descriptor(name)
            data, column = self._extract_plot_data(descriptor)
            parsed.append((descriptor, params, data, column))
        
        time_markers = self._collect_map_time_markers(parsed)

        fig = plt.figure(figsize=figsize or (16, 4 * len(parsed)))
        outer_grid = fig.add_gridspec(len(parsed), 1)

        axes: list[plt.Axes] = []

        for idx, (descriptor, params, data, column) in enumerate(parsed):
            subplot_spec = outer_grid[idx]

            if descriptor.plot_type == "map":
                normalized_name = self._normalize_name(descriptor.name)

                if isinstance(data, dict) and data:
                    plot_times = params.get("time")

                    if plot_times is None:
                        plot_times = [sorted(data.keys())[0]]

                    if isinstance(plot_times, str):
                        plot_times = [plot_times]

                    prepared_times: list[datetime] = []

                    for plot_time in plot_times:
                        if isinstance(plot_time, str):
                            prepared_time = datetime.strptime(
                                plot_time,
                                "%Y-%m-%d %H:%M:%S",
                            ).replace(tzinfo=timezone.utc)
                        elif isinstance(plot_time, datetime):
                            prepared_time = plot_time
                        else:
                            raise ValueError(
                                f"Unsupported time value type: {type(plot_time)!r}"
                            )

                        if prepared_time not in data:
                            raise ValueError(
                                f"Time '{prepared_time}' is unavailable for map '{descriptor.name}'."
                            )

                        prepared_times.append(prepared_time)

                    ncols = int(params.get("ncols", 2))
                    nrows = max(1, ceil(len(prepared_times) / ncols))

                    inner_grid = GridSpecFromSubplotSpec(
                        nrows,
                        ncols,
                        subplot_spec=subplot_spec,
                        wspace=0.08,
                        hspace=0.25,
                    )

                    for map_idx, plot_time in enumerate(prepared_times):
                        ax = self._add_map_axis(
                            fig=fig,
                            inner_grid=inner_grid,
                            map_idx=map_idx,
                            maps_count=len(prepared_times),
                            ncols=ncols,
                        )

                        if normalized_name == "gim":
                            plot_gim_map_on_ax(
                                ax,
                                data[plot_time],
                                title=f"{descriptor.name} ({plot_time})",
                                cmap=params.get("cmap", "jet"),
                            )
                        else:
                            limits = (
                                (0.0, 80.0)
                                if normalized_name in {"adjusted tec", "tec adjusted"}
                                else (0.0, 1.0)
                            )

                            plot_simurg_map_on_ax(
                                ax,
                                data[plot_time],
                                title=f"{descriptor.name} ({plot_time})",
                                cmap=params.get("cmap", "jet"),
                                point_size=params.get("s", 8),
                                colorbar_limits=limits,
                            )

                        axes.append(ax)

                else:
                    ax = fig.add_subplot(
                        subplot_spec,
                        projection=ccrs.PlateCarree(),
                    )
                    self._plot_map(ax, descriptor, data, params)
                    axes.append(ax)

            else:
                timeseries_params = dict(params)
                timeseries_params["time_markers"] = time_markers

                source_axes = self._plot_source_timeseries(
                    fig=fig,
                    subplot_spec=subplot_spec,
                    descriptor=descriptor,
                    data=data,
                    params=timeseries_params,
                )
                if source_axes is not None:
                    axes.extend(source_axes)
                    continue

                ax = fig.add_subplot(subplot_spec)

                if descriptor.plot_type == "histogram":
                    self._plot_histogram(ax, descriptor, data, column, params)
                else:
                    self._plot_timeseries(ax, descriptor, data, column, timeseries_params)

                axes.append(ax)

        fig.tight_layout()
        return fig, axes
