from __future__ import annotations

from typing import Any, Iterable

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import cartopy.crs as ccrs
from cartopy import feature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER

import math

import pandas as pd


def panel_labels(n: int) -> list[str]:
    """Returns a list of panel labels: a, b, c, ... (n items)."""
    if n < 0:
        raise ValueError("n must be non-negative")

    alphabet = "abcdefghijklmnopqrstuvwxyz"
    if n > len(alphabet):
        raise ValueError(f"n must be <= {len(alphabet)}")

    return list(alphabet[:n])


def _nice_step(y_range: float) -> float:
    """Pick a 'nice' tick step based on data range."""
    if y_range <= 0 or math.isnan(y_range):
        return 1.0
    raw = y_range / 5.0
    magnitude = 10 ** math.floor(math.log10(raw))
    norm = raw / magnitude
    if norm <= 1:
        step = 1
    elif norm <= 2:
        step = 2
    elif norm <= 2.5:
        step = 2.5
    elif norm <= 5:
        step = 5
    else:
        step = 10
    return step * magnitude


def auto_ylim_and_ticks(y: pd.Series, target_ticks: int = 5) -> tuple[tuple[float, float], list[float]]:
    """Automatic limits and ticks (publication-ish) without per-file tweaking."""
    y = y.dropna()
    if y.empty:
        return (-1, 1), [-1, 0, 1]

    ymin = float(y.min())
    ymax = float(y.max())

    if math.isclose(ymin, ymax):
        pad = 1.0 if ymin == 0 else abs(ymin) * 0.2
        lo, hi = ymin - pad, ymax + pad
        step = _nice_step(hi - lo)
    else:
        pad = 0.08 * (ymax - ymin)
        lo, hi = ymin - pad, ymax + pad
        step = _nice_step(hi - lo)

    lo_snapped = math.floor(lo / step) * step
    hi_snapped = math.ceil(hi / step) * step

    ticks = _build_ticks(lo_snapped, hi_snapped, step)

    while len(ticks) > max(target_ticks + 3, 8):
        step *= 2
        lo_snapped = math.floor(lo / step) * step
        hi_snapped = math.ceil(hi / step) * step
        ticks = _build_ticks(lo_snapped, hi_snapped, step)

    return (lo_snapped, hi_snapped), ticks


def _build_ticks(lo: float, hi: float, step: float) -> list[float]:
    ticks: list[float] = []
    t = lo
    for _ in range(500):
        if t > hi + 1e-12:
            break
        ticks.append(t)
        t += step
    return ticks

def style_axes(ax):
    for spine in ax.spines.values():
        spine.set_color("gray")
    ax.grid(True)

def kp_colors(kp_values: pd.Series) -> list[str]:
    colors: list[str] = []
    for val in kp_values:
        v = float(val)
        if v < 3.5:
            colors.append("green")
        elif 3.5 <= v <= 4.5:
            colors.append("yellow")
        else:
            colors.append("red")
    return colors


def plot_kp_index(
    ax: plt.Axes,
    kp_df: pd.DataFrame,
    *,
    datetime_col: str = "datetime",
    kp_col: str = "kp",
    width: float = 0.115,
    ylabel: str = "Kp",
    xlabel: str | None = "Day",
) -> plt.Axes:
    """Draw Kp bars on the provided axis and return the axis."""
    dt = pd.to_datetime(kp_df[datetime_col], errors="coerce")
    values = pd.to_numeric(kp_df[kp_col], errors="coerce")

    ax.bar(dt, values, color=kp_colors(values), width=width)
    ax.set_ylim(0, 9)
    ax.set_yticks([0, 3, 6, 9])
    ax.set_ylabel(ylabel, fontweight="bold")
    if xlabel:
        ax.set_xlabel(xlabel, fontweight="bold")
    return ax


def plot_dataframe_series(
    ax: plt.Axes,
    data: pd.DataFrame,
    *,
    y_col: str,
    datetime_candidates: tuple[str, ...] = ("datetime", "DateTime", "date", "time"),
    color: str | None = None,
    title: str | None = None,
    ylabel: str | None = None,
    **params: Any,
) -> plt.Axes:
    """Plot one DataFrame column as time series on a provided axis."""
    x = None
    for candidate in datetime_candidates:
        if candidate in data.columns:
            x = pd.to_datetime(data[candidate], errors="coerce")
            break

    if x is None:
        if isinstance(data.index, pd.DatetimeIndex):
            x = data.index
        else:
            x = pd.RangeIndex(start=0, stop=len(data), step=1)

    y = pd.to_numeric(data[y_col], errors="coerce")
    ax.plot(x, y, color=color, **params)

    if ylabel:
        ax.set_ylabel(ylabel)
    if title:
        ax.set_title(title)

    ax.grid(True, linestyle="--", alpha=0.35)
    return ax


def plot_structured_map(
    ax: plt.Axes,
    arr,
    *,
    cmap: str = "jet",
    point_size: float = 8,
    colorbar: bool = True,
) -> plt.Axes:
    """Plot structured map array with lat/lon/vals fields."""
    names = getattr(getattr(arr, "dtype", None), "names", None)
    if not names or not {"lat", "lon", "vals"}.issubset(set(names)):
        raise ValueError("Expected structured array with lat/lon/vals fields.")

    ax.set_global()
    ax.add_feature(feature.LAND, facecolor="lightgray")
    ax.add_feature(feature.OCEAN, facecolor="white")
    ax.add_feature(feature.COASTLINE, linewidth=0.6)

    img = ax.scatter(
        arr["lon"],
        arr["lat"],
        c=arr["vals"],
        s=point_size,
        cmap=cmap,
        transform=ccrs.PlateCarree(),
    )

    if colorbar:
        plt.colorbar(img, ax=ax, shrink=0.75, pad=0.02)

    return ax


def prepare_layout(
    ax: plt.Axes,
    lon_locator: Iterable[float] | None,
    lat_locator: Iterable[float] | None,
) -> None:
    """add coastline/borders/gridlines and format map axes."""
    gl = ax.gridlines(
        linewidth=2,
        color="gray",
        alpha=0.5,
        draw_labels=True,
        linestyle="--",
    )
    gl.top_labels = False
    gl.right_labels = False
    gl.xformatter = LONGITUDE_FORMATTER
    gl.yformatter = LATITUDE_FORMATTER

    if lon_locator:
        gl.xlocator = mticker.FixedLocator(list(lon_locator))
    if lat_locator:
        gl.ylocator = mticker.FixedLocator(list(lat_locator))

    ax.set_xlim(-180, 180)
    ax.set_ylim(-90, 90)

    ax.add_feature(feature.COASTLINE, linewidth=2.5)
    ax.add_feature(feature.BORDERS, linestyle=":", linewidth=2)
    ax.add_feature(feature.LAKES, alpha=0.5)
    ax.add_feature(feature.RIVERS)


def add_panel_label(ax: plt.Axes, label: str) -> None:
    """add subplot panel mark like 'a', 'b', ..."""
    ax.text(
        0.025,
        0.87,
        label,
        weight="bold",
        transform=ax.transAxes,
        bbox=dict(
            facecolor="white",
            edgecolor="none",
            alpha=0.8,
            boxstyle="round,pad=0.2",
        ),
    )


def add_colorbar_right(fig: plt.Figure, ax: plt.Axes, mappable, label: str) -> None:
    """place a colorbar to the right of the axes."""
    cax = fig.add_axes(
        [
            ax.get_position().x1 + 0.01,
            ax.get_position().y0,
            0.02,
            ax.get_position().height,
        ]
    )
    cbar = fig.colorbar(mappable, cax=cax)
    cbar.ax.set_ylabel(label, rotation=-90, va="bottom")
