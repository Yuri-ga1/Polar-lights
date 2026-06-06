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
    save_dir: str = os.path.join("files", "graphs"),
    map_projection: str | None = None,
    projection: str | None = None,
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
    resolved_projection_name = map_projection or projection
    nrows = max(1, ceil(len(plot_times) / ncols))
    marks = panel_labels(nrows * ncols)

    fig, axs = plt.subplots(
        figsize=(FIGSIZE_WIDTH, 16),
        nrows=nrows,
        ncols=ncols,
        subplot_kw={"projection": resolve_map_projection(resolved_projection_name)},
    )

    axs = axs.flatten() if nrows * ncols > 1 else [axs]

    for idx, ax in enumerate(axs):
        if idx >= len(plot_times):
            ax.axis("off")
            continue

        t = plot_times[idx]

        geomagnetic_lines(
            ax=ax,
            date=t.replace(tzinfo=None),
            levels= [-50, -30, 30, 50],
            color='black'
        )

        arr = data[t]
        img = plot_gim_map_on_ax(
            ax,
            arr,
            title=t.strftime(TIME_FORMAT_TITLE)[:-7] + " UT",
            cmap=cmap,
            map_projection=resolved_projection_name,
        )
        add_panel_label(ax, marks[idx])

        if (idx + 1) % ncols == 0:
            add_colorbar_right(fig, ax, img, f"TEC, {GIM_TEC_LIMITS.units}")

    os.makedirs(save_dir, exist_ok=True)

    save_name = "GIM.png"
    save_path = os.path.join(save_dir, save_name)
    fig.savefig(save_path)
    
    return fig


def plot_gim_map_on_ax(
    ax: plt.Axes,
    arr: NDArray,
    *,
    title: str,
    cmap: str = "jet",
    map_projection: str | None = None,
    projection: str | None = None,
):
    """Draw one GIM map on existing map axis."""
    lon_locator = (-180, -90, 0, 90, 180)
    lat_locator = (-80, -40, 0, 40, 80)

    prepare_layout(
        ax,
        lon_locator,
        lat_locator,
        map_projection=map_projection or projection,
    )
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
    ax.set_title(title)
    return img
