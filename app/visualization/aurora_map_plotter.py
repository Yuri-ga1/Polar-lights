import pandas as pd
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from datetime import datetime

from app.visualization.geo_utils import (
    geomagnetic_equator,
    solar_terminator
)

from app.visualization.color_utils import get_dominant_color

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

    def plot(self, time: datetime | None = None):
        """
        Строит карту мира с наблюдениями
        """
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

        # --- 3. Геомагнитный полюс ---
        if self.show_geomagnetic_equator:
            lats, lons = geomagnetic_equator()
            ax.plot(
                lons,
                lats,
                transform=ccrs.PlateCarree(),
                linewidth=1.5,
                color='orange',
                label="Geomagnetic equator"
            )

        # --- 4. Точки наблюдений ---
        if "colors" in self.df.columns:
            plot_colors = self.df["colors"].apply(get_dominant_color)
        else:
            plot_colors = "black"

        ax.scatter(
            self.df["lon"],
            self.df["lat"],
            c=plot_colors,
            s=10,
            transform=ccrs.PlateCarree(),
            label="Observations"
        )

        ax.legend(loc="lower left")
        plt.title("12-13 November 2025 observations")
        if self.save_path is None:
            plt.show()
        plt.savefig(self.save_path)