from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Dict

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from numpy.typing import NDArray

from app.visualization.geo_utils import geomagnetic_lines
from app.visualization.plot_utils import (
    add_colorbar_right,
    add_panel_label,
    panel_labels,
    prepare_layout,
)


TIME_FORMAT_TITLE = "%d %B %Y %H:%M:%S.%f"
FIGSIZE_WIDTH = 18
DEFAULT_GEOMAGNETIC_LEVELS = (-60, -15, 0, 15, 60)


@dataclass(frozen=True)
class GimColorLimits:
    vmin: float
    vmax: float
    units: str


GIM_TEC_LIMITS = GimColorLimits(0.0, 150.0, "TECU")


def _to_grid(arr: NDArray) -> tuple[NDArray, NDArray, NDArray]:
    """Convert flat structured (lat, lon, vals) data into a 2D [lat, lon] grid."""
    lats = np.sort(np.unique(arr["lat"]))
    lons = np.sort(np.unique(arr["lon"]))

    lat_index = {v: i for i, v in enumerate(lats)}
    lon_index = {v: j for j, v in enumerate(lons)}

    grid = np.full((len(lats), len(lons)), np.nan, dtype=float)
    for lat, lon, val in zip(arr["lat"], arr["lon"], arr["vals"]):
        grid[lat_index[float(lat)], lon_index[float(lon)]] = float(val)

    return lats, lons, grid


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

        if len(text) == 8 and text.count(":") == 2:
            parsed_time = datetime.strptime(text, "%H:%M:%S").time()
            return datetime.combine(base_date.date(), parsed_time)

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
    data: dict[datetime, NDArray],
    plot_times,
) -> list[datetime]:
    if not data:
        raise ValueError("GIM data is empty.")

    available_times = sorted(t.replace(tzinfo=None) for t in data.keys())
    data_by_time = {t.replace(tzinfo=None): t for t in data.keys()}
    base_date = available_times[0]

    if plot_times is None:
        return [data_by_time[t] for t in available_times]

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
                "Requested map time is not available in GIM data.\n"
                f"Requested: {requested_time:%Y-%m-%d %H:%M:%S}\n"
                f"Nearest available times: {_format_available_times(nearest)}"
            )

        resolved_times.append(data_by_time[requested_time])

    return resolved_times


def plot_gim_maps(
    data: Dict[datetime, NDArray],
    plot_times,
    ncols: int = 2,
    cmap: str = "jet",
    show_geomagnetic_lines: bool = True,
    geomagnetic_levels=DEFAULT_GEOMAGNETIC_LEVELS,
    save_dir: str = os.path.join("files", "graphs"),
) -> plt.Figure:
    """Plot GIM TEC maps for specified times."""
    if not data:
        raise ValueError("GIM data is empty.")

    plot_times = sorted(resolve_plot_times(data, plot_times))
    ncols = max(1, min(ncols, len(plot_times)))
    nrows = max(1, ceil(len(plot_times) / ncols))
    marks = panel_labels(len(plot_times))

    fig = plt.figure(figsize=(FIGSIZE_WIDTH, max(4.8, 5.0 * nrows)))
    grid = fig.add_gridspec(nrows=nrows, ncols=ncols)

    axes: list[plt.Axes] = []
    for idx in range(len(plot_times)):
        row = idx // ncols
        col = idx % ncols
        is_single_last_in_row = idx == len(plot_times) - 1 and col == 0 and ncols > 1
        spec = grid[row, :] if is_single_last_in_row else grid[row, col]
        axes.append(fig.add_subplot(spec, projection=ccrs.PlateCarree()))

    for idx, ax in enumerate(axes):

        plot_time = plot_times[idx]
        img = plot_gim_map_on_ax(
            ax,
            data[plot_time],
            title=plot_time.strftime(TIME_FORMAT_TITLE)[:-7] + " UT",
            cmap=cmap,
            plot_time=plot_time,
            show_geomagnetic_lines=show_geomagnetic_lines,
            geomagnetic_levels=geomagnetic_levels,
        )
        add_panel_label(ax, marks[idx])

        is_right_column = (idx + 1) % ncols == 0
        is_last_plot = idx == len(plot_times) - 1
        if is_right_column or is_last_plot:
            add_colorbar_right(fig, ax, img, f"TEC, {GIM_TEC_LIMITS.units}")

    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "GIM.png")
    fig.savefig(save_path, bbox_inches="tight", pad_inches=0.08)

    return fig


def plot_gim_map_on_ax(
    ax: plt.Axes,
    arr: NDArray,
    *,
    title: str,
    cmap: str = "jet",
    plot_time: datetime | None = None,
    show_geomagnetic_lines: bool = True,
    geomagnetic_levels=DEFAULT_GEOMAGNETIC_LEVELS,
):
    """Draw one GIM map on an existing map axis."""
    lon_locator = (-180, -90, 0, 90, 180)
    lat_locator = (-80, -40, 0, 40, 80)

    prepare_layout(ax, lon_locator, lat_locator)

    if plot_time is not None:
        native_time = plot_time.replace(tzinfo=None)

        if show_geomagnetic_lines:
            geomagnetic_lines(
                ax=ax,
                date=native_time,
                levels=list(geomagnetic_levels),
                color="black",
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
