from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
from matplotlib.patches import Wedge

from app.visualization.geo_utils import geomagnetic_lines, solar_terminator
from app.visualization.color_utils import get_dominant_color
from app.visualization.plot_settings import POINT_RADIUS
from app.visualization.plot_utils import apply_map_extent, resolve_map_projection

EUROPE_MAP_EXTENT = (-25.0, 45.0, 30.0, 75.0)
AMERICA_MAP_EXTENT = (-170.0, -30.0, 15.0, 75.0)
DEFAULT_AURORA_MAP_FOCUS = "europe"
AURORA_MAP_FOCUSES = {
    "europe": EUROPE_MAP_EXTENT,
    "america": AMERICA_MAP_EXTENT,
}


def resolve_aurora_map_extent(
    focus: str | None = DEFAULT_AURORA_MAP_FOCUS,
    extent: tuple[float, float, float, float] | list[float] | None = None,
) -> tuple[float, float, float, float] | None:
    """Resolve a named Aurora map focus or a custom map extent.

    ``extent`` uses ``(longitude_min, longitude_max, latitude_min,
    latitude_max)`` in degrees.  Passing ``None`` for both arguments keeps
    the full map visible.
    """
    if extent is not None:
        if len(extent) != 4:
            raise ValueError(
                "Aurora map_extent must contain four values: "
                "(lon_min, lon_max, lat_min, lat_max)."
            )
        lon_min, lon_max, lat_min, lat_max = (float(value) for value in extent)
        if not (-180 <= lon_min < lon_max <= 180):
            raise ValueError("Aurora longitude extent must satisfy -180 <= min < max <= 180.")
        if not (-90 <= lat_min < lat_max <= 90):
            raise ValueError("Aurora latitude extent must satisfy -90 <= min < max <= 90.")
        return lon_min, lon_max, lat_min, lat_max

    if focus is None:
        return None
    normalized_focus = str(focus).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "eu": "europe",
        "europe": "europe",
        "us": "america",
        "usa": "america",
        "america": "america",
        "north_america": "america",
    }
    normalized_focus = aliases.get(normalized_focus, normalized_focus)
    if normalized_focus not in AURORA_MAP_FOCUSES:
        supported = ", ".join(sorted(AURORA_MAP_FOCUSES))
        raise ValueError(f"Unknown Aurora map focus '{focus}'. Use one of: {supported}.")
    return AURORA_MAP_FOCUSES[normalized_focus]


def find_peak_aurora_time(
    df: pd.DataFrame,
    target_date: date | datetime | str,
) -> datetime:
    """Return the earliest moment with the largest number of active auroras.

    Each observation occupies the interval ``[start, start + duration]``.
    Observations are counted only for the requested calendar date.  If no
    valid observation interval exists, ``ValueError`` is raised.
    """
    if isinstance(target_date, datetime):
        day = target_date.date()
    else:
        day = pd.Timestamp(target_date).date()

    if df is None or df.empty:
        raise ValueError("Aurora dataframe is empty")

    data = df.copy()
    date_values = data.get("date", pd.Series(index=data.index, dtype=object))
    time_values = data.get("time", pd.Series(index=data.index, dtype=object))
    duration_values = data.get(
        "duration_min",
        pd.Series(0, index=data.index, dtype=float),
    )
    starts = pd.to_datetime(
        date_values.astype(str).str.strip()
        + " "
        + time_values.astype(str).str.strip(),
        errors="coerce",
    )
    durations = pd.to_numeric(duration_values, errors="coerce").fillna(0)
    durations = durations.clip(lower=0)

    day_start = pd.Timestamp(day)
    day_end = day_start + pd.Timedelta(days=1)
    events: dict[pd.Timestamp, list[int]] = {}

    for start, duration in zip(starts, durations):
        if pd.isna(start):
            continue
        finish = start + pd.to_timedelta(float(duration), unit="m")
        if finish < day_start or start >= day_end:
            continue

        clipped_start = max(start, day_start)
        clipped_finish = min(finish, day_end)
        events.setdefault(clipped_start, [0, 0])[0] += 1
        events.setdefault(clipped_finish, [0, 0])[1] += 1

    if not events:
        raise ValueError(f"There is no valid aurora data for date: {day}")

    active = 0
    peak_count = -1
    peak_time: pd.Timestamp | None = None
    for moment in sorted(events):
        starts_at, ends_at = events[moment]
        # Start events are applied first, so intervals sharing a boundary are
        # considered simultaneous at that moment.
        active += starts_at
        if active > peak_count:
            peak_count = active
            peak_time = moment
        active -= ends_at

    if peak_time is None:
        raise ValueError(f"There is no valid aurora data for date: {day}")
    return peak_time.to_pydatetime()


def plot_aurora_observations_on_ax(
    ax: plt.Axes,
    df: pd.DataFrame,
    *,
    time: datetime,
    show_geomagnetic_equator: bool = True,
    show_terminator: bool = True,
    point_radius: float = POINT_RADIUS,
    map_projection: str | None = None,
    projection: str | None = None,
    map_focus: str | None = DEFAULT_AURORA_MAP_FOCUS,
    map_extent: tuple[float, float, float, float] | list[float] | None = None,
) -> None:
    """Plot aurora observations from DataFrame on an existing map axis."""
    if time is None:
        raise ValueError("time must not be None")
    if df is None or df.empty:
        raise ValueError("Aurora dataframe is empty")

    data = df.copy()
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    target_date = time.date()
    data = data[data["date"].dt.date == target_date]
    if data.empty:
        raise ValueError(f"There is no aurora data for date: {target_date}")

    apply_map_extent(ax, map_projection or projection)
    resolved_extent = resolve_aurora_map_extent(map_focus, map_extent)
    if resolved_extent is not None:
        ax.set_extent(resolved_extent, crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND, facecolor="lightgray")
    ax.add_feature(cfeature.OCEAN, facecolor="white")
    ax.add_feature(cfeature.COASTLINE, linewidth=0.7)
    ax.add_feature(cfeature.BORDERS, linewidth=0.3)

    if show_terminator:
        solar_terminator(ax, time=time, color="black", alpha=0.35)

    if show_geomagnetic_equator:
        geomagnetic_lines(ax=ax, date=time, color="orange")
        ax.plot([], [], color="orange", linewidth=2.0, label="Geomagnetic equator (0°)")
        ax.plot([], [], color="orange", linestyle="--", linewidth=1.2, label="Geomagnetic ±30°")

    for _, row in data.iterrows():
        x, y = row["lon"], row["lat"]
        colors = row.get("colors")

        if pd.isna(colors):
            continue

        if isinstance(colors, str):
            colors = [c.strip() for c in colors.split(";") if c.strip()]
        elif isinstance(colors, (list, tuple, set)):
            colors = [str(c).strip() for c in colors if str(c).strip()]
        else:
            colors = [str(colors).strip()] if str(colors).strip() else []

        colors = [
            color
            for color in colors
            if color.lower() not in {"unknown", "unk", "none", "nan", ""}
        ]

        if not colors:
            continue

        angle_per_sector = 360 / len(colors)
        for i, color in enumerate(colors):
            facecolor = get_dominant_color(color)

            if str(facecolor).lower() in {"unknown", "unk", "none", "nan", ""}:
                continue

            wedge = Wedge(
                (x, y),
                point_radius,
                i * angle_per_sector,
                (i + 1) * angle_per_sector,
                facecolor=facecolor,
                transform=ccrs.PlateCarree(),
            )
            ax.add_patch(wedge)

    # --- Легенда для точек наблюдения ---
    handles, labels = ax.get_legend_handles_labels()

    colors_series = df["colors"].dropna().apply(lambda s: s.split(";") if isinstance(s, str) else s)

    legend_colors = max(colors_series, key=len)
    legend_colors = legend_colors[:7]

    # создаем объект для многокрасочной легенды
    auroras_patch = MulticolorPatch(legend_colors)

    # добавляем в handles и labels
    handles.append(auroras_patch)
    labels.append("Auroras")

    # создаем легенду с кастомным handler
    ax.legend(
        handles=handles,
        labels=labels,
        loc="lower left",
        handler_map={MulticolorPatch: MulticolorPatchHandler()},
        handlelength=1.5,
        handleheight=1.5,
        fontsize=24
    )

class MulticolorPatch(object):
        def __init__(self, colors):
            self.colors = colors

class MulticolorPatchHandler(object):
    def legend_artist(self, legend, orig_handle, fontsize, handlebox):
        width, height = handlebox.width, handlebox.height
        cx, cy = width/2 - handlebox.xdescent, height/2 - handlebox.ydescent
        radius = min(width, height) / 2
        n = len(orig_handle.colors)
        angle_per_sector = 360 / n
        wedges = []

        for i, c in enumerate(orig_handle.colors):
            wedge = Wedge(
                (cx, cy),
                radius,
                i * angle_per_sector,
                (i + 1) * angle_per_sector,
                facecolor=c,
                edgecolor='black',
                linewidth=0.5
            )
            wedges.append(wedge)
            handlebox.add_artist(wedge)

        return wedges

class AuroraMapPlotter:
    def __init__(
        self,
        csv_path: str,
        save_path: str | None = None,
        show_geomagnetic_equator: bool = True,
        show_terminator: bool = True,
        map_projection: str | None = None,
        projection: str | None = None,
        map_focus: str | None = DEFAULT_AURORA_MAP_FOCUS,
        map_extent: tuple[float, float, float, float] | list[float] | None = None,
    ):
        self.csv_path = csv_path
        self.save_path = save_path
        self.show_geomagnetic_equator = show_geomagnetic_equator
        self.show_terminator = show_terminator
        self.map_projection = map_projection or projection
        self.map_focus = map_focus
        self.map_extent = map_extent

        self.df = pd.read_csv(csv_path)
        self.df["date"] = pd.to_datetime(self.df["date"], errors="coerce")

    def plot(
        self,
        time: datetime,
        map_projection: str | None = None,
        projection: str | None = None,
        map_focus: str | None = None,
        map_extent: tuple[float, float, float, float] | list[float] | None = None,
    ):
        """Строит карту мира с наблюдениями."""
        fig = plt.figure(figsize=(14, 7))
        resolved_projection_name = map_projection or projection or self.map_projection
        ax = plt.axes(projection=resolve_map_projection(resolved_projection_name))

        plot_aurora_observations_on_ax(
            ax,
            self.df,
            time=time,
            show_geomagnetic_equator=self.show_geomagnetic_equator,
            show_terminator=self.show_terminator,
            point_radius=POINT_RADIUS,
            map_projection=resolved_projection_name,
            map_focus=self.map_focus if map_focus is None else map_focus,
            map_extent=self.map_extent if map_extent is None else map_extent,
        )

        ax.set_title(f"{time.strftime('%d %B %Y')} auroras")

        if self.save_path is None:
            plt.show()
        else:
            plt.savefig(self.save_path)
