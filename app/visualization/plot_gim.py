from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Dict, List

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np
from numpy.typing import NDArray

from app.visualization.geo_utils import solar_terminator
from app.visualization.plot_utils import panel_labels, prepare_layout, add_panel_label, add_colorbar_right


TIME_FORMAT_TITLE = "%d %B %Y %H:%M:%S.%f"
FIGSIZE_WIDTH = 18


@dataclass(frozen=True)
class GimColorLimits:
    vmin: float
    vmax: float
    units: str


GIM_TEC_LIMITS = GimColorLimits(0.0, 150.0, "TECU")


def _to_grid(arr: NDArray) -> tuple[NDArray, NDArray, NDArray]:
    """
    English comment:
    Convert flat structured (lat, lon, vals) into 2D grid [lat, lon] with sorted unique axes.
    """
    lats = np.unique(arr["lat"])
    lons = np.unique(arr["lon"])

    # Ensure deterministic order
    lats = np.sort(lats)
    lons = np.sort(lons)

    # Map to indices
    lat_index = {v: i for i, v in enumerate(lats)}
    lon_index = {v: j for j, v in enumerate(lons)}

    grid = np.full((len(lats), len(lons)), np.nan, dtype=float)
    for lat, lon, val in zip(arr["lat"], arr["lon"], arr["vals"]):
        i = lat_index[float(lat)]
        j = lon_index[float(lon)]
        grid[i, j] = float(val)

    return lats, lons, grid


def plot_gim_maps(
    data: Dict[datetime, NDArray],
    plot_times: List[datetime],
    ncols: int = 2,
    cmap: str = "jet",
) -> str:
    """
    Plot GIM TEC maps for specified times.

    Returns saved image path.
    """
    if not data:
        raise ValueError("Данные GIM пустые.")
    if not plot_times:
        raise ValueError("plot_times пустой.")

    plot_times = [t for t in plot_times if t in data]
    if not plot_times:
        raise ValueError("Нет данных для указанных plot_times.")

    plot_times = sorted(plot_times)
    nrows = max(1, ceil(len(plot_times) / ncols))
    marks = panel_labels(nrows * ncols)

    lon_locator = (-180, -90, 0, 90, 180)
    lat_locator = (-80, -40, 0, 40, 80)

    fig, axs = plt.subplots(
        figsize=(FIGSIZE_WIDTH, 16),
        nrows=nrows,
        ncols=ncols,
        subplot_kw={"projection": ccrs.PlateCarree()},
    )

    axs = axs.flatten() if nrows * ncols > 1 else [axs]

    for idx, ax in enumerate(axs):
        if idx >= len(plot_times):
            ax.axis("off")
            continue

        t = plot_times[idx]

        solar_terminator(
            ax,
            time=datetime(t.year, t.month, t.day, t.hour, t.minute, t.second),
            color="black",
            alpha=0.1,
        )

        prepare_layout(ax, lon_locator, lat_locator)

        arr = data[t]
        lats, lons, grid = _to_grid(arr)

        extent = (float(lons.min()), float(lons.max()), float(lats.min()), float(lats.max()))
        img = ax.imshow(
            grid,
            extent=extent,
            origin="lower",
            cmap=cmap,
            vmin=GIM_TEC_LIMITS.vmin,
            vmax=GIM_TEC_LIMITS.vmax,
            transform=ccrs.PlateCarree(),
        )

        ax.set_title(t.strftime(TIME_FORMAT_TITLE)[:-7] + " UT")
        add_panel_label(ax, marks[idx])

        # Same pattern as ROTI: put colorbar on the right column
        if (idx + 1) % ncols == 0:
            add_colorbar_right(fig, ax, img, f"TEC, {GIM_TEC_LIMITS.units}")

    save_dir = os.path.join("files", "graphs")
    os.makedirs(save_dir, exist_ok=True)

    save_name = "GIM.png"
    save_path = os.path.join(save_dir, save_name)
    fig.savefig(save_path)
    plt.close(fig)
