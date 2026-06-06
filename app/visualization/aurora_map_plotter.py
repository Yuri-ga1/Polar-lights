from __future__ import annotations

from datetime import datetime

import pandas as pd
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
from matplotlib.patches import Wedge

from app.visualization.geo_utils import geomagnetic_lines, solar_terminator
from app.visualization.color_utils import get_dominant_color
from app.visualization.plot_settings import POINT_RADIUS
from app.visualization.plot_utils import apply_map_extent, resolve_map_projection


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
    ):
        self.csv_path = csv_path
        self.save_path = save_path
        self.show_geomagnetic_equator = show_geomagnetic_equator
        self.show_terminator = show_terminator
        self.map_projection = map_projection or projection

        self.df = pd.read_csv(csv_path)
        self.df["date"] = pd.to_datetime(self.df["date"], errors="coerce")

    def plot(
        self,
        time: datetime,
        map_projection: str | None = None,
        projection: str | None = None,
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
        )

        ax.set_title(f"{time.strftime('%d %B %Y')} auroras")

        if self.save_path is None:
            plt.show()
        else:
            plt.savefig(self.save_path)
