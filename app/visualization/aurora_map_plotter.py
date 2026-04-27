from __future__ import annotations

from datetime import datetime

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Wedge

from app.visualization.color_utils import get_dominant_color
from app.visualization.geo_utils import geomagnetic_lines, solar_terminator
from app.visualization.plot_settings import POINT_RADIUS


class MulticolorPatch:
    def __init__(self, colors):
        self.colors = colors


class MulticolorPatchHandler:
    def legend_artist(self, legend, orig_handle, fontsize, handlebox):
        width, height = handlebox.width, handlebox.height
        cx, cy = width / 2 - handlebox.xdescent, height / 2 - handlebox.ydescent
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
                edgecolor="black",
                linewidth=0.5,
            )
            wedges.append(wedge)
            handlebox.add_artist(wedge)

        return wedges


def _parse_colors(raw_colors) -> list[str]:
    if pd.isna(raw_colors):
        return ["black"]
    if isinstance(raw_colors, str):
        colors = [c.strip() for c in raw_colors.split(";") if c.strip()]
        return colors or ["black"]
    return ["black"]


def plot_aurora_dataframe(
    df: pd.DataFrame,
    time: datetime,
    *,
    ax: plt.Axes | None = None,
    show_geomagnetic_equator: bool = True,
    show_terminator: bool = True,
) -> tuple[plt.Figure, plt.Axes]:
    """
    Plot aurora observations from DataFrame on provided axis (or create a new figure).
    Expected columns: date, lat, lon, colors.
    """
    if time is None:
        raise ValueError("time must not be None")

    data = df.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    target_date = time.date()
    day_df = data[data["date"].dt.date == target_date]
    if day_df.empty:
        raise ValueError(f"There is no data for date: {target_date}")

    if ax is None:
        fig = plt.figure(figsize=(14, 7))
        ax = plt.axes(projection=ccrs.PlateCarree())
    else:
        fig = ax.figure

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

    for _, row in day_df.iterrows():
        x, y = row["lon"], row["lat"]
        colors = _parse_colors(row.get("colors"))
        angle_per_sector = 360 / len(colors)

        for i, color in enumerate(colors):
            wedge = Wedge(
                (x, y),
                POINT_RADIUS,
                i * angle_per_sector,
                (i + 1) * angle_per_sector,
                facecolor=get_dominant_color(color),
                transform=ccrs.PlateCarree(),
            )
            ax.add_patch(wedge)

    handles, labels = ax.get_legend_handles_labels()
    colors_series = day_df.get("colors", pd.Series(dtype=object)).dropna().apply(
        lambda s: s.split(";") if isinstance(s, str) else ["black"]
    )
    if not colors_series.empty:
        legend_colors = max(colors_series, key=len)[:7]
        handles.append(MulticolorPatch(legend_colors))
        labels.append("Auroras")

    if handles:
        ax.legend(
            handles=handles,
            labels=labels,
            loc="lower left",
            handler_map={MulticolorPatch: MulticolorPatchHandler()},
            handlelength=1.5,
            handleheight=1.5,
            fontsize=24,
        )

    ax.set_title(f"{time.strftime('%d %B %Y')} auroras")
    return fig, ax


class AuroraMapPlotter:
    def __init__(
        self,
        csv_path: str,
        save_path: str = None,
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
        """
        Строит карту мира с наблюдениями
        """
        fig, _ = plot_aurora_dataframe(
            self.df,
            time,
            show_geomagnetic_equator=self.show_geomagnetic_equator,
            show_terminator=self.show_terminator,
        )
        if self.save_path is None:
            plt.show()
        else:
            fig.savefig(self.save_path)
        return fig
