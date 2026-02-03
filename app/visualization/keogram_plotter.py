from __future__ import annotations
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import matplotlib.pyplot as plt

from app.visualization.plot_settings import set_plt_def_params
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


def _normalize_utc(dt_: datetime) -> datetime:
    return dt_.replace(tzinfo=dt_.tzinfo or timezone.utc).astimezone(timezone.utc)


def _date_range(d0: date, d1: date) -> list[date]:
    if d1 < d0:
        raise ValueError("day_finish < day_start")
    days = (d1 - d0).days
    return [d0 + timedelta(days=i) for i in range(days + 1)]


def _build_times_utc(day_start: date, day_finish: date, cfg: KeogramConfig) -> list[datetime]:
    """Генерирует сетку времени, как в старом Keogram.py (каждые time_step_min минут)."""
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
        raise ValueError("Ожидается structured numpy array с полями lat/lon/vals, но dtype.names отсутствует.")
    missing = [f for f in fields if f not in names]
    if missing:
        raise ValueError(f"В данных отсутствуют поля: {missing}. Есть только: {list(names)}")


def build_keogram_matrix(
    data: dict[datetime, np.ndarray],
    day_start: date,
    day_finish: date,
    cfg: KeogramConfig,
) -> tuple[np.ndarray, list[datetime], np.ndarray]:
    """
    Возвращает:
    - matrix: shape (n_lat_bins, n_times), значения ROTI (nanmean по точкам в широтной полосе)
    - times: список datetime (UTC) по оси X
    - lat_centers: центры широтных полос по оси Y
    """
    if not data:
        raise ValueError("Данные SIMuRG пустые.")

    first_arr = next(iter(data.values()))
    _require_fields(first_arr)

    times_all = _build_times_utc(day_start, day_finish, cfg)

    times = [t for t in times_all if _normalize_utc(t) in data]
    if not times:
        raise ValueError("В выбранном диапазоне времени нет данных (ключей datetime) в словаре data.")

    step = float(cfg.lat_step_deg)
    edges = np.arange(90.0, -90.0 - 1e-9, -step)
    lat_centers = (edges[:-1] + edges[1:]) / 2.0

    matrix = np.full((len(lat_centers), len(times)), np.nan, dtype=float)

    for ti, t in enumerate(times):
        arr = data[_normalize_utc(t)]
        lat = np.asarray(arr["lat"], dtype=float)
        lon = np.asarray(arr["lon"], dtype=float)
        val = np.asarray(arr["vals"], dtype=float)

        good = np.isfinite(lat) & np.isfinite(lon) & np.isfinite(val) & (val != 0)
        good &= _hemisphere_mask(lon, cfg.hemisphere)

        if not np.any(good):
            continue

        lat_g = lat[good]
        val_g = val[good]

        for li in range(len(lat_centers)):
            top = edges[li]
            bot = edges[li + 1]
            in_band = (lat_g <= top) & (lat_g > bot)
            if np.any(in_band):
                matrix[li, ti] = float(np.nanmean(val_g[in_band]))

    return matrix, times, lat_centers


def plot_keogram(
    data: dict[datetime, np.ndarray],
    day_start: date,
    day_finish: date,
    cfg: Optional[KeogramConfig] = None,
) -> Path:
    """
    Строит и сохраняет кеограмму из данных SIMuRG (как roti_plotter: вход — dict[datetime, NDArray]).
    """
    cfg = cfg or KeogramConfig()

    matrix, times, lat_centers = build_keogram_matrix(data, day_start, day_finish, cfg)

    fig = plt.figure(figsize=(30, 15))
    ax = plt.axes()

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

    # --- X axis ticks: always 7 labels, evenly spaced ---
    n_labels = 7
    x_min = 0
    x_max = len(times) - 1

    tick_pos = np.linspace(x_min, x_max, n_labels, dtype=int)

    tick_labels: list[str] = []
    for i, p in enumerate(tick_pos):
        t = times[p]

        if i % 2 == 0:
            label = t.strftime("%H:%M\n%d %B %Y")
        else:
            label = t.strftime("%H:%M")

        tick_labels.append(label)

    ax.set_xticks(tick_pos)
    ax.set_xticklabels(tick_labels)
    ax.tick_params(axis="x", pad=18)

    add_colorbar_right(fig=fig, ax=ax, mappable=im, label=cfg.colorbar_label)
    fig.subplots_adjust(right=0.90)

    save_dir = os.path.join("files", "graphs")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "keogram.png")

    fig.savefig(save_path, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)

