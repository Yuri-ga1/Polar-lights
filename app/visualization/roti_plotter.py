from __future__ import annotations

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

from app.visualization.geo_utils import solar_terminator, geomagnetic_lines
from app.visualization.plot_utils import panel_labels, prepare_layout, add_panel_label, add_colorbar_right

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


MapParams = namedtuple("MapParams", ["point_size", "point_marker", "cmap"], defaults=[10, "s", "jet"])

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

def plot_map(
    data: dict[datetime, np.ndarray],
    plot_times: list[datetime],
    product_type: str = "roti",
    save_dir: str = os.path.join("files", "graphs"),
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

    nrows = max(1, ceil(len(plot_times) / ncols))
    subplot_marks = panel_labels(nrows * ncols)

    fig, axs = plt.subplots(
        figsize=(18, 16),
        nrows=nrows,
        ncols=ncols,
        subplot_kw={"projection": ccrs.PlateCarree()}
    )

    axs = axs.flatten() if nrows * ncols > 1 else [axs]

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
            title=time.strftime(TIME_FORMAT_TITLE)[:-7] + " UT",
            cmap=map_params.cmap,
            point_size=map_params.point_size,
            plot_time=time,
            colorbar_limits=(color_limits.min, color_limits.max),
            show_colorbar=False,
        )

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
    save_path = os.path.join(save_dir, f"{product.hdf_name.upper()}.png")

    fig.savefig(
        save_path,
        bbox_inches="tight",
        pad_inches=0.08,
    )
    return fig


def plot_simurg_map_on_ax(
    ax,
    arr,
    title=None,
    plot_time=None,
    cmap="jet",
    point_size=8,
    colorbar_limits=None,
    colorbar_label: str | None = None,
    show_terminator=True,
    show_geomagnetic_lines=True,
    geomagnetic_levels=[-60, -15, 0, 15, 60],
    show_colorbar=True,
    cbar_ax=None,
):
    ...
    """Draw one SIMuRG map (ROTI/Adjusted TEC-like structured array) on a given axis."""
    lon_locator = (-180, -90, 0, 90, 180)
    lat_locator = (-80, -40, 0, 40, 80)

    prepare_layout(ax, lon_locator, lat_locator)

    if plot_time is not None:
        native_time = plot_time.replace(tzinfo=None)

        if show_terminator:
            solar_terminator(
                ax,
                time=native_time,
                color="black",
                alpha=0.1,
            )

        if show_geomagnetic_lines:
            geomagnetic_lines(
                ax=ax,
                date=native_time,
                levels=list(geomagnetic_levels),
                color="black",
            )

    sctr = ax.scatter(
        arr["lon"],
        arr["lat"],
        c=arr["vals"],
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
        cbar = plt.colorbar(sctr, cax=cbar_ax, ax=ax)
        if colorbar_label:
            cbar.set_label(colorbar_label)

    ax.set_title(title)
    return sctr
