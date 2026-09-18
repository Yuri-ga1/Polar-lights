from __future__ import annotations

from datetime import timedelta

import astropy.units as u
import matplotlib.patheffects as path_effects
import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.text import Text
from matplotlib.transforms import Bbox

from app.solar.models import SolarDiskData, utc_datetime


def plot_solar_disk_on_ax(ax, data: SolarDiskData):
    """Draw on WCSAxes created with ``projection=data.solar_map``; return ax."""
    solar_map, config = data.solar_map, data.config
    if not hasattr(ax, "coords"):
        raise ValueError(
            "Solar disk needs WCSAxes: fig.add_subplot(..., projection=data.solar_map)"
        )
    values = solar_map.data.astype(np.float32)
    # Chunk the WCS transform to avoid allocating full 4096² SkyCoord objects.
    for start in range(0, values.shape[0], 128):
        y, x = np.mgrid[start : min(start + 128, values.shape[0]), : values.shape[1]]
        world = solar_map.pixel_to_world(x * u.pix, y * u.pix)
        radius = np.hypot(world.Tx.to_value(u.arcsec), world.Ty.to_value(u.arcsec))
        values[start : start + y.shape[0]][
            radius > solar_map.rsun_obs.to_value(u.arcsec)
        ] = np.nan
    valid = values[np.isfinite(values)]
    if not valid.size:
        raise ValueError("HMI image contains no valid on-disk pixels")
    cmap = LinearSegmentedColormap.from_list(
        "hmi_orange", ["#050000", "#713000", "#da7000", "#ffaf22", "#ffe078"]
    )
    cmap.set_bad("black")
    image = ax.imshow(
        values,
        origin="lower",
        cmap=cmap,
        norm=Normalize(vmin=0, vmax=float(np.percentile(valid, 99.8))),
        interpolation="nearest",
    )
    ax.set_facecolor("black")
    ax.set_aspect("equal")
    ax.set_box_aspect(1)
    ax.grid(False)
    for index, label in enumerate(("X (arcsec)", "Y (arcsec)")):
        coord = ax.coords[index]
        coord.set_format_unit(u.arcsec)
        coord.set_major_formatter("s")
        coord.set_axislabel(label, fontsize=12)
        coord.set_ticks(spacing=500 * u.arcsec)
        coord.set_ticklabel(size=10)
    # Use the complete JP2 footprint, including its metadata-defined disk center.
    ax.set_xlim(-0.5, values.shape[1] - 0.5)
    ax.set_ylim(-0.5, values.shape[0] - 0.5)
    actual = utc_datetime(data.metadata["observation_time"])
    display_time = actual + timedelta(microseconds=500000)
    ax.set_title(f"SDO HMI {display_time:%d %b %Y %H:%M:%S} UTC", fontsize=15, pad=13)
    annotations = []
    for item in data.regions:
        annotation = ax.annotate(
            str(item.region.number),
            (item.pixel_x, item.pixel_y),
            xytext=config.label_offset,
            textcoords="offset points",
            fontsize=config.label_fontsize,
            color="white",
            weight="bold",
            arrowprops={"arrowstyle": "-", "color": "white", "lw": 0.65, "alpha": 0.8},
            path_effects=[path_effects.withStroke(linewidth=2.2, foreground="black")],
        )
        annotations.append(annotation)
    # Greedily try nearby text offsets; the scientific anchor never moves.
    ax.figure.canvas.draw()
    renderer = ax.figure.canvas.get_renderer()
    occupied = []
    anchors = [
        ax.transData.transform((item.pixel_x, item.pixel_y)) for item in data.regions
    ]
    spot_boxes = [Bbox.from_bounds(x - 5, y - 5, 10, 10) for x, y in anchors]
    dx, dy = config.label_offset
    for annotation in annotations:
        candidates = [(dx, dy)]
        for distance in (16, 28, 42, 58):
            candidates.extend(
                [
                    (dx, dy + distance),
                    (dx, dy - distance),
                    (dx - distance - 35, dy),
                    (dx + distance, dy),
                ]
            )
        best_offset, best_score = candidates[0], float("inf")
        for offset in candidates:
            annotation.set_position(offset)
            annotation.update_positions(renderer)
            # Annotation.get_window_extent includes its leader line, which can
            # force unnecessary displacement or hide real text collisions.
            box = Text.get_window_extent(annotation, renderer).expanded(1.08, 1.2)
            collisions = sum(box.overlaps(other) for other in occupied + spot_boxes)
            outside = not ax.bbox.fully_contains(
                box.x0, box.y0
            ) or not ax.bbox.fully_contains(box.x1, box.y1)
            score = collisions + 10 * outside
            if score < best_score:
                best_offset, best_score = offset, score
            if not score:
                break
        annotation.set_position(best_offset)
        annotation.update_positions(renderer)
        box = Text.get_window_extent(annotation, renderer).expanded(1.08, 1.2)
        occupied.append(box)
    if config.colorbar:
        ax.figure.colorbar(
            image, ax=ax, fraction=0.046, pad=0.04, label="JP2 display intensity"
        )
    return ax
