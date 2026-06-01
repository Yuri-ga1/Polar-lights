from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional

import matplotlib.pyplot as plt
import numpy as np

from app.visualization.plot_utils import add_colorbar_right


Hemisphere = Literal["west", "east", "all"]


@dataclass(frozen=True)
class KeogramConfig:
    lat_step_deg: float = 2.5
    time_step_min: int = 5
    hour_min: int = 0
    hour_max: int = 24
    hemisphere: Hemisphere = "west"
    cmap: str = "jet"
    vmin: float = 0.0
    vmax: float = 1.0
    colorbar_label: str = "<ROTI>,\nTECU/min"


@dataclass(frozen=True)
class KeogramData:
    matrix: np.ndarray
    times: list[datetime]
    lat_centers: np.ndarray
    cfg: KeogramConfig


def _normalize_utc(dt_: datetime) -> datetime:
    return dt_.replace(tzinfo=dt_.tzinfo or timezone.utc).astimezone(timezone.utc)

def _as_datetime_start(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value

    return datetime.combine(value, time.min)


def _as_datetime_finish(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        return value

    return datetime.combine(value, time.max)

def _date_range(d0: date, d1: date) -> list[date]:
    if d1 < d0:
        raise ValueError("day_finish < day_start")
    days = (d1 - d0).days
    return [d0 + timedelta(days=i) for i in range(days + 1)]


def _build_times_utc(day_start: date, day_finish: date, cfg: KeogramConfig) -> list[datetime]:
    times: list[datetime] = []
    for d in _date_range(day_start, day_finish):
        for hh in range(cfg.hour_min, cfg.hour_max):
            for mm in range(0, 60, cfg.time_step_min):
                times.append(datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc))
    return times


def _hemisphere_mask(lon: np.ndarray, hemi: Hemisphere) -> np.ndarray:
    if hemi == "west":
        return lon < 0
    if hemi == "east":
        return lon > 0
    return np.ones_like(lon, dtype=bool)


def _require_fields(arr: np.ndarray, fields: tuple[str, ...] = ("lat", "lon", "vals")) -> None:
    names = getattr(arr.dtype, "names", None)
    if not names:
        raise ValueError("Expected a structured numpy array with lat/lon/vals fields.")
    missing = [field for field in fields if field not in names]
    if missing:
        raise ValueError(f"Missing fields in SIMuRG data: {missing}. Available: {list(names)}")


def _build_lat_grid(cfg: KeogramConfig) -> tuple[np.ndarray, np.ndarray]:
    step = float(cfg.lat_step_deg)
    edges = np.arange(90.0, -90.0 - 1e-9, -step)
    lat_centers = (edges[:-1] + edges[1:]) / 2.0
    return edges, lat_centers


def resolve_keogram_times(
    available_times: Iterable[datetime],
    day_start: date | datetime,
    day_finish: date | datetime,
    cfg: KeogramConfig,
) -> list[datetime]:
    start_dt = _normalize_utc(_as_datetime_start(day_start))
    finish_dt = _normalize_utc(_as_datetime_finish(day_finish))

    if finish_dt < start_dt:
        raise ValueError("day_finish must be greater than or equal to day_start")

    available_utc = {_normalize_utc(t) for t in available_times}

    return [
        t
        for t in _build_times_utc(start_dt.date(), finish_dt.date(), cfg)
        if start_dt <= _normalize_utc(t) <= finish_dt
        and _normalize_utc(t) in available_utc
    ]


def _build_keogram_column(
    arr: np.ndarray,
    edges: np.ndarray,
    cfg: KeogramConfig,
) -> np.ndarray:
    _require_fields(arr)

    lat = arr["lat"]
    lon = arr["lon"]
    val = arr["vals"]

    good = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(val) & (val != 0)
    good &= _hemisphere_mask(lon, cfg.hemisphere)

    column = np.full(len(edges) - 1, np.nan, dtype=float)
    if not np.any(good):
        return column

    lat_g = np.asarray(lat[good], dtype=float)
    val_g = np.asarray(val[good], dtype=float)

    bin_index = np.floor((90.0 - lat_g) / float(cfg.lat_step_deg)).astype(np.int64)
    in_range = (bin_index >= 0) & (bin_index < column.size)
    if not np.any(in_range):
        return column

    bin_index = bin_index[in_range]
    val_g = val_g[in_range]

    sums = np.bincount(bin_index, weights=val_g, minlength=column.size)
    counts = np.bincount(bin_index, minlength=column.size)
    has_values = counts > 0
    column[has_values] = sums[has_values] / counts[has_values]

    return column


def build_keogram_matrix(
    data: dict[datetime, np.ndarray],
    day_start: date | datetime,
    day_finish: date | datetime,
    cfg: KeogramConfig,
) -> tuple[np.ndarray, list[datetime], np.ndarray]:
    if not data:
        raise ValueError("SIMuRG data is empty.")

    times = resolve_keogram_times(data.keys(), day_start, day_finish, cfg)
    if not times:
        raise ValueError("No SIMuRG data is available in the selected time range.")

    edges, lat_centers = _build_lat_grid(cfg)
    matrix = np.full((len(lat_centers), len(times)), np.nan, dtype=float)

    for ti, t in enumerate(times):
        matrix[:, ti] = _build_keogram_column(data[_normalize_utc(t)], edges, cfg)

    return matrix, times, lat_centers


def build_keogram_matrix_from_slices(
    time_slices: Iterable[tuple[datetime, np.ndarray]],
    available_times: Iterable[datetime],
    day_start: date | datetime,
    day_finish: date | datetime,
    cfg: KeogramConfig,
) -> tuple[np.ndarray, list[datetime], np.ndarray]:
    times = resolve_keogram_times(available_times, day_start, day_finish, cfg)
    if not times:
        raise ValueError("No SIMuRG data is available in the selected time range.")

    edges, lat_centers = _build_lat_grid(cfg)
    matrix = np.full((len(lat_centers), len(times)), np.nan, dtype=float)
    time_to_index = {_normalize_utc(t): idx for idx, t in enumerate(times)}

    for slice_time, arr in time_slices:
        column_index = time_to_index.get(_normalize_utc(slice_time))
        if column_index is None:
            continue

        matrix[:, column_index] = _build_keogram_column(arr, edges, cfg)

    return matrix, times, lat_centers


def plot_keogram_matrix(
    matrix: np.ndarray,
    times: list[datetime],
    lat_centers: np.ndarray,
    cfg: Optional[KeogramConfig] = None,
    save_dir: str = os.path.join("files", "graphs"),
) -> plt.Figure:
    cfg = cfg or KeogramConfig()

    fig = plt.figure(figsize=(30, 15))
    ax = plt.axes()
    plot_keogram_on_ax(ax, matrix, times, lat_centers, cfg=cfg)
    fig.subplots_adjust(right=0.90)

    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "keogram.png")
    fig.savefig(save_path, bbox_inches="tight", pad_inches=0.1)

    return fig


def plot_keogram_on_ax(
    ax: plt.Axes,
    matrix: np.ndarray,
    times: list[datetime],
    lat_centers: np.ndarray,
    cfg: Optional[KeogramConfig] = None,
) -> None:
    cfg = cfg or KeogramConfig()

    extent = (0, len(times), float(lat_centers.min()), float(lat_centers.max()))

    im = ax.imshow(
        matrix,
        origin="upper",
        aspect="auto",
        extent=extent,
        cmap=cfg.cmap,
        vmin=cfg.vmin,
        vmax=cfg.vmax,
    )

    ax.grid(linestyle="--")
    ax.set_ylabel("Latitude")
    ax.set_yticks(np.arange(-90, 91, 30))
    ax.set_xlabel("Time, UT")

    n_labels = 7
    x_min = 0
    x_max = len(times) - 1
    tick_pos = np.linspace(x_min, x_max, n_labels, dtype=int)

    tick_labels: list[str] = []
    for idx, position in enumerate(tick_pos):
        current_time = times[position]
        if idx % 2 == 0:
            tick_labels.append(current_time.strftime("%H:%M\n%d %b %Y"))
        else:
            tick_labels.append(current_time.strftime("%H:%M"))

    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_labels)
    ax.tick_params(axis="x", pad=18)

    add_colorbar_right(fig=ax.figure, ax=ax, mappable=im, label=cfg.colorbar_label)


def plot_keogram(
    data: dict[datetime, np.ndarray],
    day_start: date,
    day_finish: date,
    cfg: Optional[KeogramConfig] = None,
    save_dir: str = os.path.join("files", "graphs"),
) -> plt.Figure:
    cfg = cfg or KeogramConfig()
    matrix, times, lat_centers = build_keogram_matrix(data, day_start, day_finish, cfg)
    return plot_keogram_matrix(matrix, times, lat_centers, cfg=cfg, save_dir=save_dir)
