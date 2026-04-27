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


def plot_aurora_observations_on_ax(
    ax: plt.Axes,
    df: pd.DataFrame,
    *,
    time: datetime,
    show_geomagnetic_equator: bool = True,
    show_terminator: bool = True,
    point_radius: float = POINT_RADIUS,
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
        raise ValueError(f"There is no data for date: {target_date}")

    ax.set_global()
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
            colors = []
        elif isinstance(colors, str):
            colors = [c.strip() for c in colors.split(";")]
        if not colors:
            colors = ["black"]

        angle_per_sector = 360 / len(colors)
        for i, color in enumerate(colors):
            wedge = Wedge(
                (x, y),
                point_radius,
                i * angle_per_sector,
                (i + 1) * angle_per_sector,
                facecolor=get_dominant_color(color),
                transform=ccrs.PlateCarree(),
            )
            ax.add_patch(wedge)


class AuroraMapPlotter:
    def __init__(
        self,
        csv_path: str,
        save_path: str | None = None,
        show_geomagnetic_equator: bool = True,
        show_terminator: bool = True,
    ):
        self.csv_path = csv_path
        self.save_path = save_path
        self.show_geomagnetic_equator = show_geomagnetic_equator
        self.show_terminator = show_terminator

        self.df = pd.read_csv(csv_path)
        self.df["date"] = pd.to_datetime(self.df["date"], errors="coerce")

    def plot(self, time: datetime):
        """Строит карту мира с наблюдениями."""
        fig = plt.figure(figsize=(14, 7))
        ax = plt.axes(projection=ccrs.PlateCarree())

        plot_aurora_observations_on_ax(
            ax,
            self.df,
            time=time,
            show_geomagnetic_equator=self.show_geomagnetic_equator,
            show_terminator=self.show_terminator,
            point_radius=POINT_RADIUS,
        )

        ax.set_title(f"{time.strftime('%d %B %Y')} auroras")

        if self.save_path is None:
            plt.show()
        else:
            plt.savefig(self.save_path)
