from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

import matplotlib.pyplot as plt
import pandas as pd
import math

import matplotlib.dates as mdates
from matplotlib.ticker import FixedLocator, FixedFormatter
from matplotlib.gridspec import GridSpecFromSubplotSpec
from matplotlib.offsetbox import AnchoredOffsetbox, HPacker, TextArea

from app.visualization.aurora_map_plotter import plot_aurora_observations_on_ax
from app.visualization.gim_plotter import (
    DEFAULT_GEOMAGNETIC_LEVELS,
    plot_gim_map_on_ax,
)
from app.visualization.ionosonde_plotter import plot_ionosonde_series_on_ax
from app.visualization.keogram_plotter import KeogramData, plot_keogram_on_ax
from app.visualization.plot_constructor_pack.models import (
    TIME_COLUMN_CANDIDATES,
    PlotDescriptor,
    PlotPanel,
)
from app.visualization.plot_constructor_pack.panels import PlotPanelBuilder
from app.visualization.plot_constructor_pack.registry import PlotRegistry
from app.visualization.plot_utils import (
    fill_negative_values,
    plot_histogram_on_ax,
    plot_kp_bars,
    plot_timeseries_on_ax,
    resolve_map_projection,
)
from app.visualization.roti_plotter import (
    format_simurg_map_title,
    get_product_colorbar_config,
    plot_simurg_map_on_ax,
)


class PlotRenderer:
    LEFT_YLABEL_X = -0.075
    RIGHT_YLABEL_X = 1.075

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
    
    @staticmethod
    def format_timeseries_label(name: str) -> str:
        normalized = PlotRegistry.normalize_name(name)

        labels = {
            "dst": "Dst",
            "symh": "SYM-H",
            "sym h": "SYM-H",
            "speed": "Vsw",
            "density": "Density",
            "flow pressure": "Flow pressure",
            "bx": "Bx",
            "by": "By",
            "bz": "Bz",
        }

        return labels.get(normalized, str(name))

    @staticmethod
    def get_timeseries_unit(name: str) -> str | None:
        normalized = PlotRegistry.normalize_name(name)

        units = {
            "dst": "nT",
            "symh": "nT",
            "sym h": "nT",
            "bx": "nT",
            "by": "nT",
            "bz": "nT",
            "speed": "km/s",
            "density": "cm⁻³",
            "flow pressure": "nPa",
        }

        return units.get(normalized)

    @classmethod
    def format_timeseries_ylabel(cls, fields: list[str], side: str | None = None) -> str:
        labels: list[str] = []

        for field in fields:
            label = cls.format_timeseries_label(field)
            unit = cls.get_timeseries_unit(field)

            if unit:
                labels.append(f"{label}, {unit}")
            else:
                labels.append(label)

        return " / ".join(labels)
    
    @classmethod
    def _make_colored_ylabel_box(
        cls,
        ax: plt.Axes,
        labels: list[str],
        colors: list[str],
        *,
        side: str,
    ) -> AnchoredOffsetbox:
        children = []
        textprops = {
            "fontsize": plt.rcParams["axes.labelsize"],
            "fontweight": plt.rcParams["axes.labelweight"],
            "rotation": 90,
        }

        for idx, (label, color) in enumerate(zip(labels, colors)):
            if idx > 0:
                children.append(
                    TextArea(
                        " / ",
                        textprops={
                            **textprops,
                            "color": "black",
                        },
                    )
                )

            children.append(
                TextArea(
                    label,
                    textprops={
                        **textprops,
                        "color": color,
                    },
                )
            )

        box = HPacker(
            children=children,
            align="center",
            pad=0,
            sep=2,
        )

        if side == "right":
            return AnchoredOffsetbox(
                loc="center left",
                child=box,
                pad=0,
                frameon=False,
                bbox_to_anchor=(cls.RIGHT_YLABEL_X, 0.5),
                bbox_transform=ax.transAxes,
                borderpad=0,
            )

        return AnchoredOffsetbox(
            loc="center right",
            child=box,
            pad=0,
            frameon=False,
            bbox_to_anchor=(cls.LEFT_YLABEL_X, 0.5),
            bbox_transform=ax.transAxes,
            borderpad=0,
        )

    @classmethod
    def set_colored_timeseries_ylabel(
        cls,
        ax: plt.Axes,
        fields: list[str],
        colors: list[str],
        *,
        side: str = "left",
    ) -> None:
        labels = []

        for field in fields:
            label = cls.format_timeseries_label(field)
            unit = cls.get_timeseries_unit(field)

            if unit:
                labels.append(f"{label}, {unit}")
            else:
                labels.append(label)

        ax.set_ylabel("")

        ylabel_box = cls._make_colored_ylabel_box(
            ax,
            labels,
            colors,
            side=side,
        )

        ax.add_artist(ylabel_box)

    @classmethod
    def align_ylabels(cls, ax: plt.Axes) -> None:
        ax.yaxis.set_label_coords(cls.LEFT_YLABEL_X, 0.5)

        if hasattr(ax, "_right_axis_for_label_alignment"):
            ax._right_axis_for_label_alignment.yaxis.set_label_coords(
                cls.RIGHT_YLABEL_X,
                0.5,
            )

    @classmethod
    def apply_x_range(cls, ax: plt.Axes, params: dict[str, Any]) -> None:
        x_range = cls.resolve_x_range(params)
        if x_range is None:
            return

        x_start, x_end = x_range
        ax.set_xlim(x_start.to_pydatetime(), x_end.to_pydatetime())

    @staticmethod
    def _format_constructor_date_label(value: pd.Timestamp) -> str:
        return value.strftime("%d %b %Y")

    @classmethod
    def _build_date_axis_ticks(
        cls,
        x_start: pd.Timestamp,
        x_end: pd.Timestamp,
    ) -> tuple[list[pd.Timestamp], list[str]]:
        ticks: list[pd.Timestamp] = []
        labels: list[str] = []

        for day_start in pd.date_range(x_start.normalize(), x_end.normalize(), freq="D"):
            visible_start = max(x_start, pd.Timestamp(day_start))
            visible_end = min(x_end, pd.Timestamp(day_start) + pd.Timedelta(days=1))

            if visible_end <= visible_start:
                continue

            ticks.append(visible_start + (visible_end - visible_start) / 2)
            labels.append(cls._format_constructor_date_label(pd.Timestamp(day_start)))

        return ticks, labels

    @classmethod
    def _apply_date_axis_labels(
        cls,
        ax: plt.Axes,
        x_start: pd.Timestamp,
        x_end: pd.Timestamp,
    ) -> None:
        ticks, labels = cls._build_date_axis_ticks(x_start, x_end)
        date_axis = ax.secondary_xaxis("bottom")
        date_axis.spines["bottom"].set_position(("outward", 28))
        date_axis.spines["bottom"].set_visible(False)
        date_axis.xaxis.set_major_locator(FixedLocator(mdates.date2num(ticks)))
        date_axis.xaxis.set_major_formatter(FixedFormatter(labels))
        date_axis.tick_params(axis="x", length=0, pad=3, labelbottom=True)

    @staticmethod
    def _choose_hour_step(days_count: int) -> int:
        if days_count <= 2:
            return 3

        if days_count <= 5:
            return 6

        return 12

    @classmethod
    def _build_time_axis_ticks(
        cls,
        x_start: pd.Timestamp,
        x_end: pd.Timestamp,
        hour_step: int | None = None,
    ) -> tuple[list[pd.Timestamp], list[str]]:
        if x_end <= x_start:
            return [x_start], [x_start.strftime("%H") + "\n" + cls._format_constructor_date_label(x_start)]

        day_starts = pd.date_range(
            x_start.normalize(),
            x_end.normalize(),
            freq="D",
        )

        days_count = max(1, len(day_starts))
        if hour_step is None:
            hour_step = cls._choose_hour_step(days_count)

        hour_ticks = pd.date_range(
            x_start.floor("h"),
            x_end.ceil("h"),
            freq=f"{hour_step}h",
        )

        ticks: list[pd.Timestamp] = []

        for tick in hour_ticks:
            if x_start <= tick <= x_end:
                ticks.append(pd.Timestamp(tick))

        for day_start in day_starts:
            if x_start <= day_start <= x_end:
                ticks.append(pd.Timestamp(day_start))

        ticks = sorted(set(ticks))

        labels = [tick.strftime("%H") for tick in ticks]

        return ticks, labels

    @classmethod
    def apply_bar_time_xaxis_format(
        cls,
        ax: plt.Axes,
        params: dict[str, Any],
        *,
        time_values: pd.Series | pd.DatetimeIndex | None = None,
        pad_hours: float = 1.5,
    ) -> None:
        x_range = cls.resolve_x_range(params)

        if x_range is None:
            if time_values is None:
                return

            values = pd.to_datetime(time_values, errors="coerce")
            values = pd.Series(values).dropna()

            if values.empty:
                return

            x_start = pd.Timestamp(values.min())
            x_end = pd.Timestamp(values.max())
        else:
            x_start, x_end = x_range

        pad = pd.Timedelta(hours=pad_hours)
        x_start_padded = x_start - pad
        x_end_padded = x_end + pad

        ticks, labels = cls._build_time_axis_ticks(
            x_start,
            x_end,
            hour_step=params.get("bar_hour_step", 6),
        )

        ax.set_xlim(x_start_padded.to_pydatetime(), x_end_padded.to_pydatetime())
        ax.xaxis.set_major_locator(FixedLocator(mdates.date2num(ticks)))
        ax.xaxis.set_major_formatter(FixedFormatter(labels))
        ax.tick_params(axis="x", pad=5, labelbottom=True)
        cls._apply_date_axis_labels(ax, x_start, x_end)

    @classmethod
    def apply_time_xaxis_format(
        cls,
        ax: plt.Axes,
        params: dict[str, Any],
        *,
        hour_step: int | None = None,
        time_values: pd.Series | pd.DatetimeIndex | None = None,
    ) -> None:
        x_range = cls.resolve_x_range(params)

        if x_range is None:
            if time_values is None:
                return

            values = pd.to_datetime(time_values, errors="coerce")
            values = pd.Series(values).dropna()

            if values.empty:
                return

            x_start = pd.Timestamp(values.min())
            x_end = pd.Timestamp(values.max())
        else:
            x_start, x_end = x_range

        ticks, labels = cls._build_time_axis_ticks(x_start, x_end, hour_step=hour_step)

        ax.set_xlim(x_start.to_pydatetime(), x_end.to_pydatetime())
        ax.xaxis.set_major_locator(FixedLocator(mdates.date2num(ticks)))
        ax.xaxis.set_major_formatter(FixedFormatter(labels))
        ax.tick_params(axis="x", pad=5, labelbottom=True)
        cls._apply_date_axis_labels(ax, x_start, x_end)

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
        return f"{plot_time.strftime('%d %B %Y %H:%M:%S UT')}\n{name}"
    
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
                map_projection=params.get("map_projection", params.get("projection")),
                plot_time=plot_time,
                show_geomagnetic_lines=params.get("show_geomagnetic_lines", True),
                geomagnetic_levels=params.get(
                    "geomagnetic_levels",
                    DEFAULT_GEOMAGNETIC_LEVELS,
                ),
            )
            return

        product_type = (
            "tec_adjusted"
            if normalized_name in {"adjusted tec", "tec adjusted"}
            else "roti"
        )

        colorbar_config = get_product_colorbar_config(product_type)
        product_title = "TEC Adjusted" if product_type == "tec_adjusted" else "ROTI"

        plot_simurg_map_on_ax(
            ax,
            arr,
            title=format_simurg_map_title(product_title, plot_time),
            plot_time=plot_time,
            cmap=params.get("cmap", "jet"),
            point_size=params.get("s", params.get("point_size", 6)),
            colorbar_limits=(colorbar_config.min, colorbar_config.max),
            colorbar_label=params.get("colorbar_label", colorbar_config.units),
            show_terminator=params.get("show_terminator", True),
            show_geomagnetic_lines=params.get("show_geomagnetic_lines", True),
            geomagnetic_levels=params.get("geomagnetic_levels", [-50, -30, 0, 30, 50]),
            show_colorbar=params.get("show_colorbar", True),
            cbar_ax=params.get("cbar_ax"),
            show_noon_line=params.get("show_noon_line", False),
            noon_line_color=params.get("noon_line_color", "purple"),
            noon_line_linestyle=params.get("noon_line_linestyle", "--"),
            noon_line_linewidth=params.get("noon_line_linewidth", 1.2),
            noon_line_alpha=params.get("noon_line_alpha", 0.9),
            terminator_height_km=params.get("terminator_height_km", 300.0),
            hide_zero_values=params.get("hide_zero_values", True),
            high_values_on_top=params.get("high_values_on_top", True),
            map_projection=params.get("map_projection", params.get("projection")),
            magnetic_coordinates=params.get("magnetic_coordinates", False),
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
            ncols + 1,
            subplot_spec=subplot_spec,
            width_ratios=[1] * ncols + [0.035],
            wspace=0.08,
            hspace=0.25,
        )

        axes: list[plt.Axes] = []
        cbar_ax = fig.add_subplot(inner_grid[0, -1])
        map_projection = panel.params.get("map_projection", panel.params.get("projection"))

        for map_idx, plot_time in enumerate(map_times):
            if len(map_times) == 1 and ncols_requested > 1:
                ax = fig.add_subplot(
                    inner_grid[0, :ncols],
                    projection=resolve_map_projection(map_projection),
                )
            else:
                ax = fig.add_subplot(
                    inner_grid[0, map_idx],
                    projection=resolve_map_projection(map_projection),
                )

            params = dict(panel.params)

            if map_idx == len(map_times) - 1:
                params["cbar_ax"] = cbar_ax
                params["show_colorbar"] = True
            else:
                params["show_colorbar"] = False

            self.draw_map_on_axis(
                ax=ax,
                descriptor=panel.descriptor,
                data=panel.data,
                plot_time=plot_time,
                params=params,
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

            if isinstance(time_value, (list, tuple, set)):
                if not time_value:
                    time_value = None
                else:
                    time_value = list(time_value)[0]

            if time_value is None:
                date_col = pd.to_datetime(data.get("date"), errors="coerce").dropna()
                if date_col.empty:
                    raise ValueError(
                        f"Map plot '{descriptor.name}' requires a valid 'date' column "
                        "for aurora observations."
                    )

                time_value = pd.Timestamp(date_col.iloc[0]).to_pydatetime()
            else:
                time_value = pd.to_datetime(time_value, errors="coerce")

                if pd.isna(time_value):
                    raise ValueError(
                        f"Invalid time value for aurora observations map: "
                        f"{params.get('time')!r}. Use YYYY-MM-DD HH:MM:SS."
                    )

                time_value = pd.Timestamp(time_value).to_pydatetime()

            plot_aurora_observations_on_ax(
                ax,
                data,
                time=time_value,
                show_geomagnetic_equator=params.get("show_geomagnetic_equator", True),
                show_terminator=params.get("show_terminator", True),
                point_radius=params.get("point_radius", 1.0),
                map_projection=params.get("map_projection", params.get("projection")),
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
            if not isinstance(data, pd.DataFrame):
                raise ValueError("Kp plot requires pandas DataFrame data.")

            plot_kp_bars(
                ax=ax,
                kp_df=data,
                set_xlabel=False,
                label_kwargs={
                    "fontsize": plt.rcParams["axes.labelsize"],
                    "fontweight": plt.rcParams["axes.labelweight"],
                },
            )
            ax.set_title("Kp")

            time_col = self.registry.find_time_column(data)
            if time_col is not None:
                self.apply_bar_time_xaxis_format(
                    ax,
                    params,
                    time_values=data[time_col],
                    pad_hours=params.get("bar_x_pad_hours", 1.5),
                )
            else:
                self.apply_x_range(ax, params)

            return

        plot_histogram_on_ax(
            ax,
            series,
            bins=params.get("bins", 9),
            color=params.get("color", "tab:green"),
            title=descriptor.name,
        )

        if isinstance(data, pd.DataFrame):
            time_col = self.registry.find_time_column(data)
            if time_col is not None:
                self.apply_time_xaxis_format(ax, params, time_values=data[time_col])
            else:
                self.apply_x_range(ax, params)
        else:
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
            
            if PlotRegistry.normalize_name(descriptor.source_key) == "ionosonde":
                plot_ionosonde_series_on_ax(
                    ax,
                    data,
                    time_col=time_col,
                    value_col=y_col,
                    value_label=params.get("value_label", y_col),
                    x_as_hours=False,
                    color=params.get("color", "black"),
                    linewidth=params.get("linewidth", 1.5),
                    ylabel=params.get("ylabel", y_col),
                    show_min=params.get("show_min", True),
                    show_max=params.get("show_max", True),
                    show_extrema=params.get("show_extrema"),
                )
                self.apply_time_xaxis_format(ax, params, time_values=data[time_col])
                self.draw_time_markers(ax, params)
                return

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
            self.apply_time_xaxis_format(ax, params, time_values=data[time_col])

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
        self.apply_time_xaxis_format(ax, panel.params, time_values=panel.data[time_col])
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

        if descriptor.plot_type == "keogram":
            if not isinstance(data, KeogramData):
                raise ValueError("Keogram panel requires KeogramData.")

            plot_keogram_on_ax(
                ax,
                data.matrix,
                data.times,
                data.lat_centers,
                cfg=data.cfg,
            )
            ax.set_title(panel.panel_name or descriptor.name)
            return

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

        default_colors = plt.rcParams["axes.prop_cycle"].by_key().get("color", [])
        resolved_fields: list[tuple[pd.DataFrame, str, str, str]] = []

        for idx, field in enumerate(fields):
            source_df, source_column, source_name = self._find_field_source(str(field))

            colors_param = panel.params.get("colors", {})
            color = None

            if isinstance(colors_param, dict):
                for key, value in colors_param.items():
                    if PlotRegistry.normalize_name(key) == PlotRegistry.normalize_name(source_column):
                        color = value
                        break

            if color is None:
                color = default_colors[idx % len(default_colors)] if default_colors else "black"

            resolved_fields.append((source_df, source_column, source_name, color))

        split_index = (len(resolved_fields) + 1) // 2

        left_fields = resolved_fields[:split_index]
        right_fields = resolved_fields[split_index:]

        def _plot_fields_on_axis(
            target_ax: plt.Axes,
            items: list[tuple[pd.DataFrame, str, str, str]],
        ) -> None:
            for source_df, source_column, _source_name, color in items:
                time_col = self.registry.find_time_column(source_df)
                if time_col is None:
                    raise ValueError(
                        f"Field '{source_column}' source has no time column."
                    )

                label = self.format_timeseries_label(source_column)

                fill_negative_values(
                    target_ax,
                    source_df[time_col],
                    source_df[source_column],
                    label=source_column,
                    color=panel.params.get("fill_color", "lightskyblue"),
                    alpha=panel.params.get("fill_alpha", 0.45),
                )

                target_ax.plot(
                    source_df[time_col],
                    source_df[source_column],
                    color=color,
                    linewidth=panel.params.get("linewidth", 1.5),
                    label=label,
                    zorder=2,
                )

        _plot_fields_on_axis(ax, left_fields)

        if right_fields:
            ax_r = ax.twinx()
            ax._right_axis_for_label_alignment = ax_r

            _plot_fields_on_axis(ax_r, right_fields)

            right_ylabel = panel.params.get("right_ylabel")

            if right_ylabel:
                ax_r.set_ylabel(right_ylabel)
            else:
                self.set_colored_timeseries_ylabel(
                    ax_r,
                    [source_column for _, source_column, _, _ in right_fields],
                    [color for _, _, _, color in right_fields],
                    side="right",
                )

            ax_r.grid(False)
            ax_r.spines["top"].set_visible(False)

            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax_r.get_legend_handles_labels()
            ax_r.legend(
                h1 + h2,
                l1 + l2,
                loc=panel.params.get("legend_loc", "upper right"),
            )
        else:
            ax.legend(loc=panel.params.get("legend_loc", "upper right"))

        ax.set_title(panel.panel_name or panel.descriptor.name)

        left_ylabel = panel.params.get("ylabel")

        if left_ylabel:
            ax.set_ylabel(left_ylabel)
        else:
            self.set_colored_timeseries_ylabel(
                ax,
                [source_column for _, source_column, _, _ in left_fields],
                [color for _, _, _, color in left_fields],
                side="left",
            )

        ax.grid(True, alpha=0.3)

        first_df, _, _ = self._find_field_source(str(fields[0]))
        first_time_col = self.registry.find_time_column(first_df)

        if first_time_col is not None:
            self.apply_time_xaxis_format(
                ax,
                panel.params,
                time_values=first_df[first_time_col],
            )
        else:
            self.apply_x_range(ax, panel.params)

        if right_fields:
            ax_r.set_xlim(ax.get_xlim())

        self.draw_time_markers(ax, panel.params)
