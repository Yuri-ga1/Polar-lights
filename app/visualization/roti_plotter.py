from __future__ import annotations

import gc
import os
from collections import namedtuple
from datetime import datetime
from enum import Enum
from math import ceil
from typing import Iterable, NamedTuple
import pandas as pd

import cartopy.crs as ccrs
from cartopy import feature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from app.visualization.geo_utils import solar_terminator, geomagnetic_lines
from app.visualization.plot_utils import (
    add_colorbar_right,
    add_panel_label,
    panel_labels,
    prepare_layout,
    resolve_map_projection,
)

TIME_FORMAT_TITLE = "%d %B %Y %H:%M:%S.%f"
FIGSIZE_WIDTH = 18


class ColorLimits(NamedTuple):
    min: float
    max: float
    units: str


class DataProduct(NamedTuple):
    long_name: str
    hdf_name: str
    color_limits: ColorLimits


class DataProducts(DataProduct, Enum):
    roti = DataProduct(
        "ROTI",
        "roti",
        ColorLimits(0, 1, "TECU/min"),
    )
    tec_adjusted = DataProduct(
        "TEC Adjusted",
        "tec_adjusted",
        ColorLimits(0, 80, "TEC, TECU"),
    )


MapParams = namedtuple("MapParams", ["point_size", "point_marker", "cmap"], defaults=[6, "s", "jet"])

def _resolve_product(product_type: str) -> DataProduct:
    try:
        return DataProducts[product_type].value
    except KeyError as error:
        supported = ", ".join(DataProducts.__members__.keys())
        raise ValueError(f"Неизвестный тип продукта: {product_type}. Поддерживаются: {supported}") from error

def get_product_colorbar_config(product_type: str) -> ColorLimits:
    product = _resolve_product(product_type)
    return product.color_limits

def _format_available_times(times: list[datetime]) -> str:
    return ", ".join(t.strftime("%Y-%m-%d %H:%M:%S") for t in times)


def _nearest_times(
    target: datetime,
    available_times: list[datetime],
    count: int = 2,
) -> list[datetime]:
    return sorted(
        available_times,
        key=lambda t: abs((t - target).total_seconds()),
    )[:count]


def _parse_plot_time_value(value, base_date: datetime) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().replace(tzinfo=None)

    if isinstance(value, str):
        text = value.strip()

        # Format: "HH:MM:SS"
        if len(text) == 8 and text.count(":") == 2:
            parsed_time = datetime.strptime(text, "%H:%M:%S").time()
            return datetime.combine(base_date.date(), parsed_time)

        # Format: "YYYY-MM-DD HH:MM:SS" or pandas-compatible datetime
        parsed = pd.to_datetime(text, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(
                f"Invalid plot time '{value}'. Use 'HH:MM:SS' or "
                "'YYYY-MM-DD HH:MM:SS'."
            )

        return pd.Timestamp(parsed).to_pydatetime().replace(tzinfo=None)

    raise ValueError(
        f"Unsupported plot time type: {type(value)!r}. Use datetime, "
        "pd.Timestamp, 'HH:MM:SS' or 'YYYY-MM-DD HH:MM:SS'."
    )


def _iter_chunked(values: Iterable, chunk_size: int) -> Iterable[list]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")

    chunk: list = []
    for value in values:
        chunk.append(value)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []

    if chunk:
        yield chunk


def _iter_map_slices(data) -> Iterable[tuple[datetime, np.ndarray]]:
    if isinstance(data, dict):
        for plot_time in sorted(data.keys()):
            yield plot_time, data[plot_time]
        return

    yield from data


def resolve_plot_times(
    data: dict[datetime, np.ndarray],
    plot_times,
) -> list[datetime]:
    if not data:
        raise ValueError("SIMuRG data is empty.")

    available_times = sorted(t.replace(tzinfo=None) for t in data.keys())
    data_by_time = {t.replace(tzinfo=None): t for t in data.keys()}
    base_date = available_times[0]

    if plot_times is None:
        return available_times

    if isinstance(plot_times, (str, datetime, pd.Timestamp)):
        raw_times = [plot_times]
    else:
        raw_times = list(plot_times)

    if not raw_times:
        raise ValueError("plot_times is empty.")

    resolved_times: list[datetime] = []

    for raw_time in raw_times:
        requested_time = _parse_plot_time_value(raw_time, base_date)

        if requested_time not in data_by_time:
            nearest = _nearest_times(requested_time, available_times, count=2)

            raise ValueError(
                "Requested map time is not available in SIMuRG data.\n"
                f"Requested: {requested_time:%Y-%m-%d %H:%M:%S}\n"
                "SIMuRG data step is usually 30 seconds, but some moments "
                "may be absent because of source data gaps.\n"
                f"Nearest available times: {_format_available_times(nearest)}"
            )

        resolved_times.append(data_by_time[requested_time])

    return resolved_times


def format_simurg_map_title(product_name: str, plot_time: datetime) -> str:
    return f"{plot_time.strftime(TIME_FORMAT_TITLE)[:-7]} UT\n{product_name}"


def _normalize_longitude(value: float) -> float:
    return ((value + 180) % 360) - 180


def _solar_noon_longitude(plot_time: datetime) -> float:
    time_without_tz = plot_time.replace(tzinfo=None)
    utc_hours = (
        time_without_tz.hour
        + time_without_tz.minute / 60
        + time_without_tz.second / 3600
        + time_without_tz.microsecond / 3_600_000_000
    )
    return _normalize_longitude(15 * (12 - utc_hours))


def draw_solar_noon_line_on_ax(
    ax,
    plot_time: datetime,
    *,
    color: str = "tab:orange",
    linestyle: str = "--",
    linewidth: float = 5,
    alpha: float = 0.9,
) -> None:
    """Draw the longitude where local solar time is 12:00 for the map timestamp."""
    noon_lon = _solar_noon_longitude(plot_time)
    ax.plot(
        [noon_lon, noon_lon],
        [-90, 90],
        color=color,
        linestyle=linestyle,
        linewidth=linewidth,
        alpha=alpha,
        zorder=4,
        transform=ccrs.PlateCarree(),
    )


def plot_map(
    data: dict[datetime, np.ndarray],
    plot_times: Iterable[datetime | str] | datetime | str | pd.Timestamp | None = None,
    product_type: str = "roti",
    save_dir: str = os.path.join("files", "graphs"),
    *,
    save_name: str | None = None,
    show_noon_line: bool = False,
    noon_line_color: str = "purple",
    terminator_height_km: float = 300.0,
    show_panel_labels: bool = True,
    hide_zero_values: bool = True,
    high_values_on_top: bool = True,
    point_size: float | None = None,
    map_projection: str | None = None,
    projection: str | None = None,
) -> plt.Figure:
    """
    Plotting data on globe (or part of globe).
    """

    product = _resolve_product(product_type)
    ncols = 2
    map_params = MapParams()
    colorbar_limit_scaling = 1
    fig_width = FIGSIZE_WIDTH

    def scale_color_limits(data_product: DataProduct, scale: float) -> ColorLimits:
        return ColorLimits(
            data_product.color_limits.min * scale,
            data_product.color_limits.max * scale,
            data_product.color_limits.units,
        )

    if not data:
        raise ValueError("Данные SIMuRG пустые.")

    plot_times = resolve_plot_times(data, plot_times)
    plot_times = sorted(plot_times)
    resolved_projection_name = map_projection or projection
    ncols = min(ncols, len(plot_times))

    nrows = max(1, ceil(len(plot_times) / ncols))
    subplot_marks = panel_labels(nrows * ncols)

    fig = Figure(figsize=(18, 16))
    FigureCanvasAgg(fig)
    axs = fig.subplots(
        nrows=nrows,
        ncols=ncols,
        subplot_kw={"projection": resolve_map_projection(resolved_projection_name)},
    )

    axs = np.atleast_1d(axs).ravel().tolist()

    for axs_index, ax1 in enumerate(axs):
        if axs_index >= len(plot_times):
            ax1.axis("off")
            continue

        time = plot_times[axs_index]

        color_limits = scale_color_limits(product, colorbar_limit_scaling)
        arr = data[time]

        sctr = plot_simurg_map_on_ax(
            ax1,
            arr,
            title=format_simurg_map_title(product.long_name, time),
            cmap=map_params.cmap,
            point_size=point_size if point_size is not None else map_params.point_size,
            plot_time=time,
            colorbar_limits=(color_limits.min, color_limits.max),
            show_colorbar=False,
            show_noon_line=show_noon_line,
            noon_line_color=noon_line_color,
            terminator_height_km=terminator_height_km,
            hide_zero_values=hide_zero_values,
            high_values_on_top=high_values_on_top,
            map_projection=resolved_projection_name,
        )

        if show_panel_labels:
            add_panel_label(ax=ax1, label=subplot_marks[axs_index])

        is_right_column = (axs_index + 1) % ncols == 0
        is_last_plot = axs_index == len(plot_times) - 1

        if is_right_column or is_last_plot:
            cbar_label = product.color_limits.units
            add_colorbar_right(
                fig=fig,
                ax=ax1,
                mappable=sctr,
                label=cbar_label,
            )

    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, save_name or f"{product.hdf_name.upper()}.png")

    fig.savefig(
        save_path,
        bbox_inches="tight",
        pad_inches=0.08,
    )
    return fig


def plot_all_maps(
    data: dict[datetime, np.ndarray] | Iterable[tuple[datetime, np.ndarray]],
    product_type: str = "roti",
    save_dir: str = os.path.join("files", "graphs"),
    *,
    maps_per_figure: int = 4,
    show_noon_line: bool = False,
    noon_line_color: str = "purple",
    terminator_height_km: float = 300.0,
    hide_zero_values: bool = True,
    high_values_on_top: bool = True,
    point_size: float | None = None,
    map_projection: str | None = None,
    projection: str | None = None,
    keep_figures: bool = False,
    collect_garbage_every: int = 1,
) -> str:
    """
    Plot all available SIMuRG maps, split into saved figures for notebook workflows.

    Returns the output directory path. Set keep_figures=True to keep figures open for display.
    """
    product = _resolve_product(product_type)
    wrote_any = False

    for group_index, time_group in enumerate(
        _iter_chunked(_iter_map_slices(data), maps_per_figure),
        start=1,
    ):
        first_time = time_group[0][0].strftime("%Y%m%d_%H%M%S")
        if len(time_group) == 1:
            save_name = f"{product.hdf_name.upper()}_{first_time}.png"
        else:
            last_time = time_group[-1][0].strftime("%Y%m%d_%H%M%S")
            save_name = f"{product.hdf_name.upper()}_{first_time}_{last_time}.png"

        fig = None
        group_data = None
        group_times = None
        try:
            group_times = [plot_time for plot_time, _arr in time_group]
            group_data = dict(time_group)

            fig = plot_map(
                data=group_data,
                plot_times=group_times,
                product_type=product_type,
                save_dir=save_dir,
                save_name=save_name,
                show_noon_line=show_noon_line,
                noon_line_color=noon_line_color,
                terminator_height_km=terminator_height_km,
                show_panel_labels=maps_per_figure != 1,
                hide_zero_values=hide_zero_values,
                high_values_on_top=high_values_on_top,
                point_size=point_size,
                map_projection=map_projection or projection,
            )
            wrote_any = True

        finally:
            if not keep_figures and fig is not None:
                fig.clear()
                plt.close(fig)

            del fig
            group_data = None
            group_times = None
            time_group.clear()

            if (
                collect_garbage_every > 0
                and group_index % collect_garbage_every == 0
            ):
                gc.collect()

    if collect_garbage_every > 0:
        gc.collect()

    if not wrote_any:
        raise ValueError("SIMuRG data is empty.")

    return save_dir


def plot_simurg_map_on_ax(
    ax,
    arr,
    title=None,
    plot_time=None,
    cmap="jet",
    point_size=6,
    colorbar_limits=None,
    colorbar_label: str | None = None,
    show_terminator=True,
    show_geomagnetic_lines=True,
    geomagnetic_levels=[-60, -15, 0, 15, 60],
    show_colorbar=True,
    cbar_ax=None,
    show_noon_line=False,
    noon_line_color="purple",
    noon_line_linestyle="--",
    noon_line_linewidth=2.5,
    noon_line_alpha=0.9,
    terminator_height_km=300.0,
    hide_zero_values=True,
    high_values_on_top=True,
    map_projection: str | None = None,
    projection: str | None = None,
):
    ...
    """Draw one SIMuRG map (ROTI/Adjusted TEC-like structured array) on a given axis."""
    lon_locator = (-180, -90, 0, 90, 180)
    lat_locator = (-80, -40, 0, 40, 80)

    prepare_layout(
        ax,
        lon_locator,
        lat_locator,
        map_projection=map_projection or projection,
    )

    if plot_time is not None:
        native_time = plot_time.replace(tzinfo=None)

        if show_terminator:
            solar_terminator(
                ax,
                time=native_time,
                color="black",
                alpha=0.1,
                height_km=terminator_height_km,
            )

        if show_geomagnetic_lines:
            geomagnetic_lines(
                ax=ax,
                date=native_time,
                levels=list(geomagnetic_levels),
                color="black",
            )

        if show_noon_line:
            draw_solar_noon_line_on_ax(
                ax,
                native_time,
                color=noon_line_color,
                linestyle=noon_line_linestyle,
                linewidth=noon_line_linewidth,
                alpha=noon_line_alpha,
            )

    points = arr
    if hide_zero_values:
        points = points[points["vals"] != 0]

    if high_values_on_top:
        points = np.sort(points, order="vals")

    sctr = ax.scatter(
        points["lon"],
        points["lat"],
        c=points["vals"],
        alpha=1,
        marker="s",
        s=point_size,
        zorder=3,
        vmin=colorbar_limits[0],
        vmax=colorbar_limits[1],
        cmap=cmap,
        transform=ccrs.PlateCarree(),
    )

    if show_colorbar:
        cbar = ax.figure.colorbar(sctr, cax=cbar_ax, ax=ax)
        if colorbar_label:
            cbar.set_label(colorbar_label)

    ax.set_title(title)
    return sctr
