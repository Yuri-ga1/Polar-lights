from __future__ import annotations

import os
from collections import namedtuple
from datetime import datetime
from enum import Enum
from math import ceil
from typing import Iterable, NamedTuple

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


MapParams = namedtuple("MapParams", ["point_size", "point_marker", "cmap"], defaults=[10, "s", "jet"])


def plot_map(data: dict[datetime, np.ndarray], plot_times: list[datetime]) -> None:
    """
    Plotting data on globe (or part of globe).
    """

    product = DataProducts.roti
    ncols = 2
    lon_locator = (-180, -90, 0, 90, 180)
    lat_locator = (-80, -40, 0, 40, 80)
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

    if not plot_times:
        raise ValueError("plot_times пустой.")

    plot_times = [t for t in plot_times if t in data]
    if not plot_times:
        raise ValueError("Нет данных для указанных plot_times.")

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
        solar_terminator(
            ax1,
            time=datetime(time.year, time.month, time.day, time.hour, time.minute, time.second),
            color="black",
            alpha=0.1,
        )
        # geomagnetic_lines(
        #     ax=ax1,
        #     date=time,
        #     levels=[-60, -30, 0, 30, 60]
        # )

        arr = data[time]
        lats = arr["lat"]
        lons = arr["lon"]
        values = arr["vals"]

        prepare_layout(ax1, lon_locator, lat_locator)

        color_limits = scale_color_limits(product, colorbar_limit_scaling)
        sctr = ax1.scatter(
            lons,
            lats,
            c=values,
            alpha=1,
            marker=map_params.point_marker,
            s=map_params.point_size,
            zorder=3,
            vmin=color_limits.min,
            vmax=color_limits.max,
            cmap=map_params.cmap,
        )

        ax1.set_title(
            time.strftime(TIME_FORMAT_TITLE)[:-7] + " UT",
        )
        add_panel_label(ax=ax1, label=subplot_marks[axs_index])

        if (axs_index + 1) % ncols == 0:
            cbar_label = f"TECU/min"
            add_colorbar_right(
                fig=fig,
                ax=ax1,
                mappable=sctr,
                label=cbar_label
            )

    save_dir = os.path.join("files", "graphs")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "ROTI.png")

    fig.savefig(save_path)
    plt.close(fig)
