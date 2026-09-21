"""Manual plume tracking using great-circle angular displacement.

Speed is the central angle between boundary centers divided by elapsed hours.
Direction is the initial great-circle bearing. All timestamps are UTC.
The drawn longitude/latitude triangle is an optional geometric aid only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np


def utc_time(value: str | datetime) -> datetime:
    """Parse a full ISO datetime; interpret a naive datetime as UTC."""
    if isinstance(value, str):
        if "T" not in value and " " not in value:
            raise ValueError("Укажите полную дату и время, например 2026-01-20 08:00:00.")
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime):
        raise ValueError("Время должно быть datetime или строкой с полной датой и временем.")
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def boundary_points(line) -> np.ndarray:
    """Validate ordered (lon, lat) vertices and unwrap the date line.

    Consecutive identical vertices are ignored. A boundary must be local
    (longitude span < 180 degrees), so its path is unambiguous.
    """
    points = np.array(line, dtype=float, copy=True)
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 2:
        raise ValueError("Граница: минимум две точки [(долгота, широта), ...].")
    if not np.isfinite(points).all():
        raise ValueError("Координаты границы должны быть конечными числами.")
    if np.any(np.abs(points[:, 0]) > 180) or np.any(np.abs(points[:, 1]) > 90):
        raise ValueError("Долгота должна быть в [-180, 180], широта — в [-90, 90].")
    points[:, 0] = np.rad2deg(np.unwrap(np.deg2rad(points[:, 0])))
    if np.ptp(points[:, 0]) >= 180:
        raise ValueError("Используйте локальную границу с размахом долгот меньше 180°.")
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    points = points[np.r_[True, lengths > 1e-12]]
    if len(points) < 2:
        raise ValueError("Граница имеет нулевую длину; нужны две различные точки.")
    return points


def _midpoint(points: np.ndarray) -> np.ndarray:
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    cumulative = np.r_[0.0, np.cumsum(lengths)]
    halfway = cumulative[-1] / 2
    segment = min(np.searchsorted(cumulative, halfway, side="right") - 1, len(lengths) - 1)
    fraction = (halfway - cumulative[segment]) / lengths[segment]
    return points[segment] + fraction * (points[segment + 1] - points[segment])


def boundary_center(line) -> np.ndarray:
    """Return the point halfway along the polyline in the degree plane.

    Unlike averaging vertices, this stays on the boundary and is invariant
    to inserting vertices on an existing segment. Longitude may be unwrapped.
    """
    return _midpoint(boundary_points(line))


def spherical_displacement(first, second) -> tuple[float, float | None]:
    """Central angle (degrees) and initial bearing clockwise from true north.

    atan2(sin(angle), cos(angle)) is stable near both coincidence and antipodes.
    The east/north terms describe the initial tangent direction on the sphere.
    A bearing is undefined for coincident/antipodal points and at a start pole.
    """
    coordinates = np.asarray([first, second], dtype=float)
    if coordinates.shape != (2, 2) or not np.isfinite(coordinates).all():
        raise ValueError("Нужны две конечные пары (долгота, широта).")
    if np.any(np.abs(coordinates[:, 1]) > 90):
        raise ValueError("Широта должна быть в [-90, 90].")
    lat1, lat2 = np.deg2rad(coordinates[:, 1])
    delta_lon = np.deg2rad((coordinates[1, 0] - coordinates[0, 0] + 180) % 360 - 180)
    east = np.cos(lat2) * np.sin(delta_lon)
    north = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(delta_lon)
    dot = np.sin(lat1) * np.sin(lat2) + np.cos(lat1) * np.cos(lat2) * np.cos(delta_lon)
    distance = float(np.rad2deg(np.arctan2(np.hypot(east, north), dot)))
    if distance < 1e-10:
        return 0.0, None
    if 180 - distance < 1e-10 or abs(np.cos(lat1)) < 1e-12:
        return distance, None
    bearing = float(np.rad2deg(np.arctan2(east, north)) % 360)
    # A tiny negative roundoff may round to 360 rather than 0 after modulo.
    return distance, 0.0 if bearing >= 360 else bearing


def great_circle_path(first, second, samples=181) -> np.ndarray | None:
    """Sample the shortest spherical arc; antipodes have no unique path."""
    if samples < 2:
        raise ValueError("Для дуги нужны минимум две точки.")
    distance, _ = spherical_displacement(first, second)
    if 180 - distance < 1e-10:
        return None
    if distance == 0:
        return np.asarray([first, second], dtype=float)
    lon, lat = np.deg2rad(np.asarray([first, second], dtype=float)).T
    vectors = np.column_stack((np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)))
    normal = np.cross(vectors[0], vectors[1])
    normal /= np.linalg.norm(normal)
    tangent = np.cross(normal, vectors[0])
    angles = np.linspace(0, np.deg2rad(distance), samples)[:, None]
    path = np.cos(angles) * vectors[0] + np.sin(angles) * tangent
    result = np.column_stack((
        np.rad2deg(np.arctan2(path[:, 1], path[:, 0])),
        np.rad2deg(np.arctan2(path[:, 2], np.hypot(path[:, 0], path[:, 1]))),
    ))
    result[0], result[-1] = first, second
    return result


def _vertical_intersection(origin, points):
    """Intersect lon=origin.lon with all segments; choose the nearest hit.

    If a segment lies on the vertical, choose its nearest point. Ties are
    resolved toward the smaller latitude, independently of vertex order.
    """
    candidates = []
    x, y = origin
    for start, end in zip(points, points[1:]):
        if abs(end[0] - start[0]) <= 1e-12:
            if abs(x - start[0]) <= 1e-12:
                candidates.append(float(np.clip(y, min(start[1], end[1]), max(start[1], end[1]))))
        else:
            fraction = (x - start[0]) / (end[0] - start[0])
            if -1e-12 <= fraction <= 1 + 1e-12:
                candidates.append(float(start[1] + np.clip(fraction, 0, 1) * (end[1] - start[1])))
    if not candidates:
        return None
    return np.array([x, min(candidates, key=lambda lat: (abs(lat - y), lat))])


@dataclass(frozen=True)
class PlumeMotion:
    time1: datetime
    time2: datetime
    line1: np.ndarray
    line2: np.ndarray
    center1: np.ndarray
    center2: np.ndarray
    intersection: np.ndarray | None
    corner: np.ndarray
    hours: float
    delta_lon: float
    delta_lat: float
    distance_deg: float
    speed_deg_h: float
    direction_deg: float | None
    direction: str

    def as_record(self) -> dict:
        def lon(value):
            return (float(value) + 180) % 360 - 180

        angle = np.deg2rad(self.direction_deg) if self.direction_deg is not None else np.nan
        east = self.speed_deg_h * np.sin(angle)
        north = self.speed_deg_h * np.cos(angle)
        if self.distance_deg == 0:
            east = north = 0.0
        return {
            "metric": "spherical_great_circle",
            "t1_UTC": self.time1,
            "t2_UTC": self.time2,
            "dt_h": self.hours,
            "lon1_deg": lon(self.center1[0]),
            "lat1_deg": self.center1[1],
            "lon2_deg": lon(self.center2[0]),
            "lat2_deg": self.center2[1],
            "intersection_lon_deg": lon(self.intersection[0]) if self.intersection is not None else np.nan,
            "intersection_lat_deg": self.intersection[1] if self.intersection is not None else np.nan,
            "corner_lon_deg": lon(self.corner[0]),
            "corner_lat_deg": self.corner[1],
            "delta_lon_deg": self.delta_lon,
            "delta_lat_deg": self.delta_lat,
            "distance_deg": self.distance_deg,
            "coordinate_lon_rate_deg_h": self.delta_lon / self.hours,
            "coordinate_lat_rate_deg_h": self.delta_lat / self.hours,
            "v_east_deg_h": east,
            "v_north_deg_h": north,
            "speed_deg_h": self.speed_deg_h,
            "direction_deg": self.direction_deg,
            "direction": self.direction,
        }


def estimate_motion(time1, line1, time2, line2) -> PlumeMotion:
    """Measure spherical center displacement; construct the optional map triangle.

    Centers retain the explicit halfway-along-the-drawn-polyline convention.
    Speed does not depend on whether the vertical intersects the second line.
    """
    time1, time2 = utc_time(time1), utc_time(time2)
    hours = (time2 - time1).total_seconds() / 3600
    if hours <= 0:
        raise ValueError("Второй момент должен быть строго позже первого.")
    first, second = boundary_points(line1), boundary_points(line2)
    c1, c2 = _midpoint(first), _midpoint(second)
    raw_delta = c2[0] - c1[0]
    delta_lon = (raw_delta + 180) % 360 - 180
    shift = delta_lon - raw_delta
    second[:, 0] += shift
    c2[0] += shift
    intersection = _vertical_intersection(c1, second)
    delta_lat = float(c2[1] - c1[1])
    distance, angle = spherical_displacement(c1, c2)
    directions = ("С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ")
    direction = (directions[int((angle + 22.5) // 45) % 8] if angle is not None
                 else "нет смещения" if distance == 0 else "азимут не определён")
    return PlumeMotion(
        time1, time2, first, second, c1, c2, intersection, np.array([c1[0], c2[1]]),
        hours, float(delta_lon), delta_lat, distance, distance / hours, angle, direction,
    )


def measure_adjacent(observations: list[dict]) -> list[PlumeMotion]:
    """Sort observations and measure consecutive pairs; never bridge missing lines."""
    ordered = sorted(observations, key=lambda item: utc_time(item["time"]))
    if len(ordered) < 2:
        raise ValueError("Для скорости нужны минимум два момента с границами плюма.")
    times = [utc_time(item["time"]) for item in ordered]
    if len(set(times)) != len(times):
        raise ValueError("Моменты наблюдений не должны повторяться.")
    missing = [str(item["time"]) for item in ordered if item.get("line") is None]
    if missing:
        raise ValueError("Сначала задайте границы для: " + ", ".join(missing))
    return [
        estimate_motion(a["time"], a["line"], b["time"], b["line"])
        for a, b in zip(ordered, ordered[1:])
    ]


def load_adjusted_tec(folder, times) -> dict:
    """Read exact requested slices from recursively discovered local SIMuRG files."""
    from app.simurg.simurg_processor import DataProduct, SimurgProcessor

    requested = sorted({utc_time(value) for value in times})
    if not requested:
        raise ValueError("Список моментов пуст.")
    files = SimurgProcessor(folder).local_files(DataProduct.TEC_ADJUSTED)
    if not files:
        raise FileNotFoundError(f"В {folder} нет tec_adjusted_*.h5. Загрузите TEC adjusted через SIMuRG.")
    data = SimurgProcessor.load_files(files, times=requested) or {}
    missing = [value for value in requested if value not in data]
    if missing:
        import h5py

        available = set()
        for path in files:
            with h5py.File(path, "r") as handle:
                if "data" in handle:
                    available.update(utc_time(key) for key in handle["data"])
        details = []
        for value in missing:
            nearest = sorted(available, key=lambda t: abs((t - value).total_seconds()))[:2]
            details.append(f"{value.isoformat()}; ближайшие: {[t.isoformat() for t in nearest]}")
        raise ValueError("Нет точных срезов TEC adjusted:\n" + "\n".join(details))
    return data


def _plot_coordinates(points, central_longitude):
    points = np.array(points, dtype=float, copy=True)
    # Shift the entire path together, preserving date-line continuity.
    points[:, 0] -= central_longitude
    points[:, 0] -= 360 * np.floor((points[:, 0].mean() + 180) / 360)
    return points


def _draw_boundary(ax, points, central_longitude, color, label, center=None):
    xy = _plot_coordinates(points, central_longitude)
    ax.plot(*xy.T, "o-", color=color, lw=2.5, ms=4, zorder=10, label=label)
    if center is not None:
        # Keep the center in the same longitude branch as its line.
        c = np.array(center, copy=True)
        c[0] += xy[0, 0] - points[0, 0]
        ax.scatter(*c, s=140, marker="X", color=color, edgecolors="black", zorder=12)


def plot_plume_map(
    data, time, line=None, *, extent=None, central_longitude=0,
    color_limits=(0, 80), point_size=6, show_colorbar=True, ax=None,
):
    """Plot TEC adjusted at ``time``, optionally with a manual geographic line.

    ``extent`` is (west, east, south, north) in geographic degrees. For a
    date-line region use e.g. (160, 200, 30, 80), central_longitude=180.
    PlateCarree keeps the degree-plane triangle visibly right-angled.
    """
    import cartopy.crs as ccrs
    import matplotlib.pyplot as plt
    from app.visualization.roti_plotter import plot_simurg_map_on_ax

    time = utc_time(time)
    key = next((key for key in data if utc_time(key) == time), None)
    if key is None:
        raise ValueError(f"Нет TEC adjusted для {time.isoformat()}.")
    projection = ccrs.PlateCarree(central_longitude=central_longitude)
    if ax is None:
        _, ax = plt.subplots(figsize=(13, 7), subplot_kw={"projection": projection})
    if ax.projection != projection:
        raise ValueError("Ось должна иметь PlateCarree с выбранной central_longitude.")
    plot_simurg_map_on_ax(
        ax, data[key], title=f"TEC adjusted · {time:%Y-%m-%d %H:%M:%S} UTC",
        plot_time=time, colorbar_limits=color_limits, colorbar_label="TEC adjusted, TECU",
        point_size=point_size, show_colorbar=show_colorbar,
        show_terminator=False, show_geomagnetic_lines=False,
    )
    # Use fixed overview coastlines/borders: zooming should not trigger downloads
    # of additional high-resolution lakes and rivers while manually annotating.
    from cartopy import feature
    from cartopy.mpl.feature_artist import FeatureArtist
    for artist in ax.findobj(FeatureArtist):
        artist.remove()
    ax.add_feature(feature.COASTLINE.with_scale("110m"), linewidth=1)
    ax.add_feature(feature.BORDERS.with_scale("110m"), linestyle=":", linewidth=0.7)
    if extent is not None:
        west, east, south, north = extent
        if not (-90 <= south < north <= 90 and 0 < east - west <= 360):
            raise ValueError("extent: west < east, -90 <= south < north <= 90.")
        middle = (west + east) / 2
        shift = central_longitude + 360 * np.floor((middle - central_longitude + 180) / 360)
        ax.set_xlim(west - shift, east - shift)
        ax.set_ylim(south, north)
    # Denser labels than the global renderer's fixed 90-degree longitude grid.
    import matplotlib.ticker as mticker
    from cartopy.mpl.gridliner import Gridliner
    for grid in ax.findobj(Gridliner):
        grid.xlocator = mticker.MaxNLocator(nbins=7)
        grid.ylocator = mticker.MaxNLocator(nbins=7)
    ax.set_aspect("equal")
    if line is not None:
        points = boundary_points(line)
        _draw_boundary(ax, points, central_longitude, "magenta", "Верхняя граница", _midpoint(points))
        ax.legend(loc="upper left")
    return ax.figure, ax


def plot_boundary_pair(data, time1, line1, time2, line2, *, ax=None, **map_kwargs):
    """Overlay two boundaries on time2, even if the vertical cannot intersect."""
    time1, time2 = utc_time(time1), utc_time(time2)
    central = map_kwargs.get("central_longitude", 0)
    fig, ax = plot_plume_map(data, time2, ax=ax, **map_kwargs)
    for time, line, color, label in (
        (time1, line1, "magenta", "t₁"), (time2, line2, "cyan", "t₂"),
    ):
        points = boundary_points(line)
        _draw_boundary(ax, points, central, color, f"{label}: {time:%m-%d %H:%M:%S}", _midpoint(points))
    ax.set_title(f"Две границы; фон TEC adjusted: {time2:%Y-%m-%d %H:%M:%S} UTC")
    ax.legend(loc="upper left")
    return fig, ax


def plot_motion_step(data, motion: PlumeMotion, step=3, *, ax=None, **map_kwargs):
    """Steps: 0 centers; 1 optional intersection; 2 map guides; 3 spherical arc.

    Both boundaries are overlaid on the *second* timestamp's TEC adjusted.
    """
    if step not in (0, 1, 2, 3):
        raise ValueError("step должен быть 0, 1, 2 или 3.")
    central = map_kwargs.get("central_longitude", 0)
    # Панель шага входит в состав общей фигуры; отдельный colorbar каждой
    # карте здесь не нужен. Общий colorbar добавляется в ячейке 8 тетради.
    map_kwargs = dict(map_kwargs)
    map_kwargs.pop("show_colorbar", None)
    fig, ax = plot_plume_map(data, motion.time2, ax=ax, show_colorbar=False, **map_kwargs)
    _draw_boundary(ax, motion.line1, central, "magenta", f"t₁: {motion.time1:%m-%d %H:%M:%S}", motion.center1)
    _draw_boundary(ax, motion.line2, central, "cyan", f"t₂: {motion.time2:%m-%d %H:%M:%S}", motion.center2)
    a, corner, b = _plot_coordinates([motion.center1, motion.corner, motion.center2], central)
    intersection = None
    if motion.intersection is not None:
        intersection = motion.intersection.copy()
        intersection[0] += a[0] - motion.center1[0]
    for name, point in (("C₁", a), ("C₂", b)):
        ax.annotate(name, point, xytext=(6, 8), textcoords="offset points", zorder=15)
    # Белый контур и почти чёрная линия видны и на тёмно-синих, и на
    # жёлто-красных областях карты TEC.
    triangle_halo = "white"
    triangle_color = "#151515"
    if step >= 1 and intersection is not None:
        ax.plot([a[0], intersection[0]], [a[1], intersection[1]], "-", color=triangle_halo,
                lw=7, zorder=12)
        ax.plot([a[0], intersection[0]], [a[1], intersection[1]], "-", color=triangle_color,
                lw=3, zorder=13, label="Вертикаль C₁ → Q (граница t₂)")
        ax.scatter(*intersection, color="yellow", edgecolors="black", s=65, zorder=14)
        if step == 1 or not np.allclose(intersection, corner, rtol=0, atol=1e-10):
            offset = (-16, -15 if intersection[1] <= corner[1] else 9)
            ax.annotate("Q", intersection, xytext=offset, textcoords="offset points", zorder=15)
    elif step in (1, 2):
        ax.text(0.02, 0.02, "Вертикаль не пересекает границу t₂.\nСферическая скорость доступна.",
                transform=ax.transAxes, zorder=20,
                bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "gray"})
    if step >= 2:
        ax.plot([a[0], corner[0]], [a[1], corner[1]], "--", color=triangle_halo,
                lw=6, zorder=13)
        ax.plot([a[0], corner[0]], [a[1], corner[1]], "--", color=triangle_color,
                lw=2.5, zorder=14, label=f"Сетка: Δφ = {motion.delta_lat:+.3f}°")
        ax.scatter(*corner, color="black", s=25, zorder=14)
        label = "P = Q" if intersection is not None and np.allclose(intersection, corner, rtol=0, atol=1e-10) else "P"
        offset = (-16, 9 if intersection is None or intersection[1] <= corner[1] else -15)
        ax.annotate(label, corner, xytext=offset, textcoords="offset points", zorder=15)
        ax.plot([corner[0], b[0]], [corner[1], b[1]], "--", color=triangle_halo,
                lw=6, zorder=13)
        ax.plot([corner[0], b[0]], [corner[1], b[1]], "--", color=triangle_color,
                lw=2.5, zorder=14, label=f"Сетка: Δλ = {motion.delta_lon:+.3f}°")
        if min(abs(motion.delta_lon), abs(motion.delta_lat)) > 1e-12:
            size = min(abs(motion.delta_lon), abs(motion.delta_lat)) * 0.18
            dx, dy = np.sign(a - corner), np.sign(b - corner)
            mark = np.array([corner + size * dx, corner + size * (dx + dy), corner + size * dy])
            ax.plot(*mark.T, color=triangle_halo, lw=4, zorder=14)
            ax.plot(*mark.T, color=triangle_color, lw=1.5, zorder=15)
    if step >= 3:
        path = great_circle_path(motion.center1, motion.center2)
        if motion.distance_deg > 0 and path is not None:
            import matplotlib.patheffects as effects

            path[:, 0] = (path[:, 0] - central + 180) % 360 - 180
            # Split at the map seam instead of drawing a line across the globe.
            breaks = np.flatnonzero(np.abs(np.diff(path[:, 0])) > 180) + 1
            split_path = np.insert(path, breaks, np.nan, axis=0)
            halo = [effects.Stroke(linewidth=7, foreground=triangle_halo), effects.Normal()]
            ax.plot(*split_path.T, color=triangle_color, lw=3, zorder=16,
                    path_effects=halo, label="Кратчайшая дуга C₁ → C₂")
            if abs(path[-1, 0] - path[-2, 0]) <= 180:
                arrow = ax.annotate("", xy=path[-1], xytext=path[-2], zorder=17,
                                    arrowprops={"arrowstyle": "-|>", "color": triangle_color, "lw": 3,
                                                "mutation_scale": 20, "shrinkA": 0, "shrinkB": 0})
                arrow.arrow_patch.set_path_effects(halo)
        angle = f"{motion.direction_deg:.1f}°" if motion.direction_deg is not None else "—"
        ax.text(0.02, 0.02,
                f"Дуга: {motion.distance_deg:.3f}° / {motion.hours:g} ч\n"
                f"v = {motion.speed_deg_h:.3f} °/ч; начальный азимут: {angle}\n"
                f"{motion.direction}",
                transform=ax.transAxes, zorder=20,
                bbox={"facecolor": "white", "alpha": 0.9, "edgecolor": "gray"})
    titles = ("Границы и центры", "Пересечение вертикали с границей t₂",
              "Вспомогательные линии координатной сетки", "Сферическое смещение C₁ → C₂")
    ax.set_title(f"{titles[step]}\nФон TEC adjusted: {motion.time2:%Y-%m-%d %H:%M:%S} UTC")
    ax.legend(loc="upper left", fontsize=9)
    return fig, ax


class BoundaryPicker:
    """Optional click input on an interactive Matplotlib map (widget or Qt).

    Left click adds a vertex, right click removes it; Enter finishes.
    Keep this object alive in the notebook and read ``picker.line`` afterward.
    """

    def __init__(self, ax, central_longitude=0):
        self.ax = ax
        self.central_longitude = central_longitude
        self.vertices = []
        self.artist, = ax.plot([], [], "o-", color="magenta", lw=2.5, zorder=15)
        self.connections = [
            ax.figure.canvas.mpl_connect("button_press_event", self._click),
            ax.figure.canvas.mpl_connect("key_press_event", self._key),
        ]

    @property
    def line(self):
        points = [[(x + self.central_longitude + 180) % 360 - 180, y] for x, y in self.vertices]
        boundary_points(points)
        return points

    def _click(self, event):
        toolbar = getattr(self.ax.figure.canvas, "toolbar", None)
        if toolbar is not None and toolbar.mode:
            return
        if event.inaxes is not self.ax or event.xdata is None or event.ydata is None:
            return
        if event.button == 1 and -90 <= event.ydata <= 90:
            self.vertices.append((event.xdata, event.ydata))
        elif event.button == 3 and self.vertices:
            self.vertices.pop()
        points = np.asarray(self.vertices).reshape(-1, 2)
        self.artist.set_data(points[:, 0], points[:, 1])
        self.ax.figure.canvas.draw_idle()

    def _key(self, event):
        if event.key == "enter":
            self.finish()

    def finish(self):
        line = self.line
        for connection in self.connections:
            self.ax.figure.canvas.mpl_disconnect(connection)
        return line
