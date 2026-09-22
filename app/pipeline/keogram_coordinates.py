from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

import numpy as np

from app.visualization.geo_utils import geographic_to_magnetic


def convert_keogram_slices_to_magnetic(
    time_slices: Iterable[tuple[datetime, np.ndarray]],
) -> Iterator[tuple[datetime, np.ndarray]]:
    """Yield SIMuRG slices with geographic ``lat``/``lon`` replaced by AACGM ones.

    A copy is made for each slice so map data cached by ``SimurgProcessor`` remains
    in geographic coordinates for any other plots.
    """
    for slice_time, source in time_slices:
        names = source.dtype.names or ()
        missing = {"lat", "lon"} - set(names)
        if missing:
            raise ValueError(
                "Cannot convert keogram coordinates: "
                f"SIMuRG slice has no {', '.join(sorted(missing))} field(s)."
            )

        converted = source.copy()
        magnetic_lat, magnetic_lon = geographic_to_magnetic(
            source["lat"], source["lon"], slice_time
        )
        converted["lat"] = magnetic_lat
        converted["lon"] = magnetic_lon
        yield slice_time, converted
