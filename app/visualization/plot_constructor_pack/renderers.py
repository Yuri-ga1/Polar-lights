from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.gridspec import GridSpecFromSubplotSpec

from app.visualization.aurora_map_plotter import plot_aurora_observations_on_ax
from app.visualization.gim_plotter import plot_gim_map_on_ax
from app.visualization.plot_constructor_pack.models import (
    TIME_COLUMN_CANDIDATES,
    PlotDescriptor,
    PlotPanel,
)
from app.visualization.plot_constructor_pack.panels import PlotPanelBuilder
from app.visualization.plot_constructor_pack.registry import PlotRegistry
from app.visualization.plot_utils import (
    plot_histogram_on_ax,
    plot_kp_bars,
    plot_timeseries_on_ax,
)
from app.visualization.roti_plotter import plot_simurg_map_on_ax


class PlotRenderer:
    def __init__(self, registry: PlotRegistry, processor_results: dict[str, Any]) -> None:
        self.registry = registry
        self.processor_results = processor_results
        self.panel_builder = PlotPanelBuilder()

    @staticmethod
    def resolve_x_range(params: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp] | None:
        left = params.get("date_start") or params.get("x_start")
        right = params.get("date_end") or params.get("x_end")

        if left is None or right is None:
            return None

        x_start = pd.to_datetime(left, errors="coerce")
        x_end = pd.to_datetime(right, errors="coerce")

        if pd.isna(x_start) or pd.isna(x_end):
            raise ValueError(
                "Invalid x-axis range. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS "
                "for date_start/date_end."
            )

        if x_end < x_start:
            raise ValueError(
                "x-axis range is invalid: date_end must be greater than or equal to date_start."
            )

        return pd.Timestamp(x_start), pd.Timestamp(x_end)

    @classmethod
    def apply_x_range(cls, ax: plt.Axes, params: dict[str, Any]) -> None:
        x_range = cls.resolve_x_range(params)
        if x_range is None:
            return

        x_start, x_end = x_range
        ax.set_xlim(x_start.to_pydatetime(), x_end.to_pydatetime())

    @staticmethod
    def draw_time_markers(ax: plt.Axes, params: dict[str, Any]) -> None:
        for marker in params.get("time_markers", []):
            marker_local = marker.tz_convert(None) if marker.tzinfo is not None else marker

            ax.axvline(
                marker_local,
                color=params.get("time_marker_color", "tab:red"),
                linestyle=params.get("time_marker_linestyle", "--"),
                linewidth=params.get("time_marker_linewidth", 1.2),
                alpha=params.get("time_marker_alpha", 0.8),
            )

    @staticmethod
    def format_map_title(name: str, plot_time: datetime) -> str:
        return f"{name} for {plot_time.strftime('%d %b %Y at %H:%M:%S UTC')}"
    
    @staticmethod
    def _format_coord(value: float, positive: str, negative: str) -> str:
        suffix = positive if value >= 0 else negative
        return f"{abs(value):.2f}°{suffix}"

    @classmethod
    def format_cosmic_ray_station_label(
        cls,
        station: str,
        station_metadata: dict[str, dict[str, float]],
    ) -> str:
        meta = station_metadata.get(station)
        if not meta:
            return station

        lat = meta.get("lat")
        lon = meta.get("lon")
        alt = meta.get("alt")

        if lat is None or lon is None:
            return station

        lat_text = cls._format_coord(lat, "N", "S")
        lon_text = cls._format_coord(lon, "E", "W")

        if alt is None:
            return f"{station} ({lat_text}, {lon_text})"

        return f"{station} ({lat_text}, {lon_text}, {alt:.0f} m)"

    def _find_field_source(self, field: str) -> tuple[pd.DataFrame, str, str]:
        normalized_field = PlotRegistry.normalize_name(field)

        for source_name, data in self.processor_results.items():
            if not isinstance(data, pd.DataFrame):
                continue

            for column in data.columns:
                if column in TIME_COLUMN_CANDIDATES:
                    continue

                if PlotRegistry.normalize_name(column) == normalized_field:
                    return data, column, source_name

        raise ValueError(f"Field '{field}' was not found in available processor results.")

    def draw_map_on_axis(
        self,
        ax: plt.Axes,
        descriptor: PlotDescriptor,
        data: dict[datetime, Any],
        plot_time: datetime,
        params: dict[str, Any],
    ) -> None:
        normalized_name = PlotRegistry.normalize_name(descriptor.name)
        arr = data[plot_time]

        if normalized_name == "gim":
            plot_gim_map_on_ax(
                ax,
                arr,
                title=self.format_map_title(descriptor.name, plot_time),
                cmap=params.get("cmap", "jet"),
            )
            return

        limits = (
            (0.0, 80.0)
            if normalized_name in {"adjusted tec", "tec adjusted"}
            else (0.0, 1.0)
        )

        plot_simurg_map_on_ax(
            ax,
            arr,
            title=self.format_map_title(descriptor.name, plot_time),
            plot_time=plot_time,
            cmap=params.get("cmap", "jet"),
            point_size=params.get("s", 8),
            colorbar_limits=limits,
            show_terminator=params.get("show_terminator", True),
            show_geomagnetic_lines=params.get("show_geomagnetic_lines", True),
            geomagnetic_levels=params.get("geomagnetic_levels", [-50, -30, 0, 30, 50]),
        )

    def plot_map_panel(
        self,
        fig: plt.Figure,
        subplot_spec,
        panel: PlotPanel,
    ) -> list[plt.Axes]:
        map_times = list(panel.map_times)

        if not map_times:
            raise ValueError(f"Map panel '{panel.descriptor.name}' has no map times.")

        ncols_requested = int(panel.params.get("ncols", 2))
        ncols = max(1, min(ncols_requested, len(map_times)))

        inner_grid = GridSpecFromSubplotSpec(
            1,
            ncols,
            subplot_spec=subplot_spec,
            wspace=0.08,
            hspace=0.25,
        )

        axes: list[plt.Axes] = []

        for map_idx, plot_time in enumerate(map_times):
            if len(map_times) == 1 and ncols_requested > 1:
                ax = fig.add_subplot(
                    inner_grid[0, :],
                    projection=ccrs.PlateCarree(),
                )
            else:
                ax = fig.add_subplot(
                    inner_grid[0, map_idx],
                    projection=ccrs.PlateCarree(),
                )

            self.draw_map_on_axis(
                ax=ax,
                descriptor=panel.descriptor,
                data=panel.data,
                plot_time=plot_time,
                params=panel.params,
            )

            axes.append(ax)

        return axes

    def plot_map_table(
        self,
        ax: plt.Axes,
        descriptor: PlotDescriptor,
        data: pd.DataFrame,
        params: dict[str, Any],
    ) -> None:
        normalized_name = PlotRegistry.normalize_name(descriptor.name)

        if normalized_name in {"aurora observation", "aurora"}:
            time_value = params.get("time")
            if time_value is None:
                date_col = pd.to_datetime(data.get("date"), errors="coerce").dropna()
                if date_col.empty:
                    raise ValueError(
                        f"Map plot '{descriptor.name}' requires a valid 'date' column "
                        "for aurora observations."
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
                f"Map plot '{descriptor.name}' requires 'lat' and 'lon' columns "
                f"in source '{descriptor.source_key}'."
            )

        raise ValueError(
            f"Map plot '{descriptor.name}' expects processor data in map dictionary "
            "format or aurora-observation table."
        )

    def plot_histogram(
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

        if PlotRegistry.normalize_name(descriptor.name) == "kp":
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
        self.apply_x_range(ax, params)

    def plot_timeseries(
        self,
        ax: plt.Axes,
        descriptor: PlotDescriptor,
        data: Any,
        column: str | None,
        params: dict[str, Any],
    ) -> None:
        if isinstance(data, pd.DataFrame):
            time_col = self.registry.find_time_column(data)

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
            self.apply_x_range(ax, params)

            self.draw_time_markers(ax, params)

            return

        if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
            ax.plot(data, color=params.get("color", "tab:blue"))
            ax.set_title(descriptor.name)
            ax.grid(True, alpha=0.3)
            return

        raise ValueError(f"Unsupported timeseries data format for plot '{descriptor.name}'.")

    def plot_cosmic_ray_single_panel(self, ax: plt.Axes, panel: PlotPanel) -> None:
        if not isinstance(panel.data, pd.DataFrame):
            raise ValueError("Cosmic ray panel requires pandas DataFrame data.")

        stations = self.panel_builder.resolve_cosmic_ray_stations(panel.data, panel.params)
        if not stations:
            raise ValueError("Cosmic ray source has no station columns to plot.")

        time_col = self.registry.find_time_column(panel.data)
        if time_col is None:
            raise ValueError(
                f"Timeseries '{panel.descriptor.name}' needs one of {TIME_COLUMN_CANDIDATES}, "
                f"but none found in '{panel.descriptor.source_key}'."
            )

        station_metadata = panel.data.attrs.get("station_metadata", {})

        for station in stations:
            ax.plot(
                panel.data[time_col],
                panel.data[station],
                linewidth=panel.params.get("linewidth", 1.5),
                label=self.format_cosmic_ray_station_label(station, station_metadata),
            )

        ax.set_title(panel.panel_name or panel.descriptor.name)
        ax.set_ylabel(panel.params.get("ylabel", "%"))
        ax.grid(True, alpha=0.3)
        ax.legend()
        self.apply_x_range(ax, panel.params)
        self.draw_time_markers(ax, panel.params)

    def plot_regular_panel(
        self,
        ax: plt.Axes,
        panel: PlotPanel,
        time_markers: list[pd.Timestamp],
    ) -> None:
        descriptor = panel.descriptor
        data = panel.data
        column = panel.column
        params = dict(panel.params)
        params["time_markers"] = time_markers

        normalized_name = PlotRegistry.normalize_name(descriptor.name)

        panel_with_markers = PlotPanel(
            descriptor=panel.descriptor,
            params=params,
            data=panel.data,
            column=panel.column,
            panel_name=panel.panel_name,
            map_times=panel.map_times,
        )

        if normalized_name == "omni" and panel.params.get("fields"):
            self.plot_omni_group_panel(ax, panel_with_markers)
            return

        if normalized_name in {"cosmic ray", "cosmic rays"} and column is None:
            self.plot_cosmic_ray_single_panel(ax, panel_with_markers)
            return

        if descriptor.plot_type == "histogram":
            self.plot_histogram(ax, descriptor, data, column, panel.params)
            return

        self.plot_timeseries(ax, descriptor, data, column, params)

        if panel.panel_name:
            ax.set_title(panel.panel_name)

    def plot_omni_group_panel(self, ax: plt.Axes, panel: PlotPanel) -> None:
        fields = panel.params.get("fields") or []

        if not fields:
            raise ValueError(f"OMNI group '{panel.panel_name}' has no fields.")

        for field in fields:
            source_df, source_column, source_name = self._find_field_source(str(field))

            time_col = self.registry.find_time_column(source_df)
            if time_col is None:
                raise ValueError(
                    f"Field '{field}' source '{source_name}' has no time column."
                )

            ax.plot(
                source_df[time_col],
                source_df[source_column],
                linewidth=panel.params.get("linewidth", 1.5),
                label=source_column,
            )

        ax.set_title(panel.panel_name or panel.descriptor.name)
        ax.set_ylabel(panel.params.get("ylabel", "value"))
        ax.grid(True, alpha=0.3)
        ax.legend()
        self.apply_x_range(ax, panel.params)
        self.draw_time_markers(ax, panel.params)