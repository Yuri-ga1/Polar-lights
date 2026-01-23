import pandas as pd
from datetime import datetime

import cartopy.crs as ccrs
import cartopy.feature as cfeature

import matplotlib.pyplot as plt
from matplotlib.patches import Wedge

from app.visualization.geo_utils import (
    geomagnetic_lines,
    solar_terminator
)
from app.visualization.color_utils import get_dominant_color
from app.visualization.plot_settings import POINT_RADIUS

class AuroraMapPlotter:
    def __init__(
        self,
        csv_path: str,
        save_path: str = None,
        show_geomagnetic_equator: bool = True,
        show_terminator: bool = True
    ):
        self.csv_path = csv_path
        self.save_path = save_path
        self.show_geomagnetic_equator = show_geomagnetic_equator
        self.show_terminator = show_terminator

        self.df = pd.read_csv(csv_path)
        self.df["date"] = pd.to_datetime(self.df["date"], errors="coerce")

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

    def plot(self, time: datetime):
        """
        Строит карту мира с наблюдениями
        """
        if time is None:
            raise ValueError("time must not be None")

        target_date = time.date()

        # фильтрация по дате
        df = self.df[self.df["date"].dt.date == target_date]
        if df.empty:
            raise ValueError(f"There is no data for date: {target_date}")

        proj = ccrs.PlateCarree()
        fig = plt.figure(figsize=(14, 7))
        ax = plt.axes(projection=proj)

        # --- 1. Материки и карта ---
        ax.set_global()
        ax.add_feature(cfeature.LAND, facecolor="lightgray")
        ax.add_feature(cfeature.OCEAN, facecolor="white")
        ax.add_feature(cfeature.COASTLINE, linewidth=0.7)
        ax.add_feature(cfeature.BORDERS, linewidth=0.3)

        # --- 2. Терминатор ---
        if self.show_terminator and time is not None:
            solar_terminator(
                ax,
                time=time,
                color="black",
                alpha=0.35
            )

        # --- 3. Геомагнитный экватор ---
        if self.show_geomagnetic_equator:
            cs0, cs30 = geomagnetic_lines(
                ax=ax,
                date=time,
                color="orange",
            )
            # Чтобы появились подписи в легенде (contour сам по себе их не дает)
            ax.plot([], [], color="orange", linewidth=2.0, label="Geomagnetic equator (0°)")
            ax.plot([], [], color="orange", linestyle="--", linewidth=1.2, label="Geomagnetic ±30°")

        # --- 4. Точки наблюдений ---
        for _, row in df.iterrows():
            x, y = row["lon"], row["lat"]
            colors = row.get("colors")
            if pd.isna(colors):
                colors = []
            elif isinstance(colors, str):
                colors = [c.strip() for c in colors.split(";")]
            if not colors:
                colors = ["black"]

            colors_count = len(colors)
            angle_per_sector = 360 / colors_count

            for i, color in enumerate(colors):
                wedge = Wedge(
                    (x, y),
                    POINT_RADIUS,
                    i * angle_per_sector,
                    (i + 1) * angle_per_sector,
                    facecolor=get_dominant_color(color),
                    transform=ccrs.PlateCarree()
                )
                ax.add_patch(wedge)

        # --- Легенда для точек наблюдения ---
        handles, labels = ax.get_legend_handles_labels()

        colors_series = df["colors"].dropna().apply(lambda s: s.split(";") if isinstance(s, str) else s)

        legend_colors = max(colors_series, key=len)
        legend_colors = legend_colors[:7]

        # создаем объект для многокрасочной легенды
        auroras_patch = self.MulticolorPatch(legend_colors)

        # добавляем в handles и labels
        handles.append(auroras_patch)
        labels.append("Auroras")

        # создаем легенду с кастомным handler
        ax.legend(
            handles=handles,
            labels=labels,
            loc="lower left",
            handler_map={self.MulticolorPatch: self.MulticolorPatchHandler()},
            handlelength=1.5,
            handleheight=1.5,
        )
        
        plt.title(f"{time.strftime("%d %B %Y")} auroras")
        if self.save_path is None:
            plt.show()
        plt.savefig(self.save_path)