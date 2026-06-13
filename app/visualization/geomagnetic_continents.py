from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cartopy.crs as ccrs
import numpy as np


DEFAULT_CONTOURS_PATH = Path(__file__).with_name("data") / "NiceWorld-180_Mlat.dat"


@lru_cache(maxsize=None)
def load_geomagnetic_contours(
    path: str | Path = DEFAULT_CONTOURS_PATH,
) -> tuple[np.ndarray, ...]:
    """Load blank-line-separated MLon/MLat contours from the four-column file."""
    contours: list[np.ndarray] = []
    current: list[tuple[float, float]] = []

    with Path(path).open(encoding="ascii") as source:
        for line_number, line in enumerate(source, start=1):
            stripped = line.strip()
            if not stripped:
                if len(current) >= 2:
                    contours.append(np.asarray(current, dtype=float))
                current = []
                continue

            if stripped.startswith("#"):
                continue

            columns = stripped.split()
            if len(columns) != 4:
                raise ValueError(
                    f"Invalid geomagnetic contour at line {line_number}: {line!r}"
                )

            magnetic_lon, magnetic_lat = map(float, columns[2:4])
            current.append((magnetic_lon, magnetic_lat))

    if len(current) >= 2:
        contours.append(np.asarray(current, dtype=float))

    if not contours:
        raise ValueError(f"No geomagnetic contours found in {path}.")

    return tuple(contours)


def _iter_valid_segments(contour: np.ndarray):
    valid = np.isfinite(contour).all(axis=1)
    start = None

    for index, is_valid in enumerate(valid):
        crosses_dateline = (
            index > 0
            and is_valid
            and valid[index - 1]
            and abs(contour[index, 0] - contour[index - 1, 0]) > 180
        )
        if not is_valid or crosses_dateline:
            if start is not None and index - start >= 2:
                yield contour[start:index]
            start = index if is_valid else None
        elif start is None:
            start = index

    if start is not None and len(contour) - start >= 2:
        yield contour[start:]


def plot_geomagnetic_continents(
    ax,
    *,
    path: str | Path = DEFAULT_CONTOURS_PATH,
    color: str = "black",
    linewidth: float = 1.5,
    zorder: float = 2.0,
):
    """Draw continent contours using the precomputed MLon/MLat columns."""
    artists = []
    for contour in load_geomagnetic_contours(path):
        for segment in _iter_valid_segments(contour):
            artists.extend(
                ax.plot(
                    segment[:, 0],
                    segment[:, 1],
                    color=color,
                    linewidth=linewidth,
                    transform=ccrs.PlateCarree(),
                    zorder=zorder,
                )
            )

    return artists
