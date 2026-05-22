import os
from typing import List

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter
import matplotlib.dates as mdates

from app.visualization.plot_utils import *

def _format_month_title(start: pd.Timestamp, end: pd.Timestamp) -> str:
    start = pd.to_datetime(start)
    end = pd.to_datetime(end)

    if start.year == end.year and start.month == end.month:
        return start.strftime("%B %Y")

    if start.year == end.year:
        return f"{start.strftime('%d %B')}–{end.strftime('%d %B')} {start.year}"

    return f"{start.strftime('%B %Y')}–{end.strftime('%B %Y')}"

def plot_cosmic_ray_variations(
    cr_df: pd.DataFrame,
    kp_df: pd.DataFrame,
    stations: List[str],
    save_dir: str = os.path.join("files", "graphs"),
):
    labels_count = len(stations)
    labels = panel_labels(labels_count)
    formatter = DateFormatter("%d")

    fig, axes = plt.subplots(labels_count+1, 1, figsize=(18, 16), sharex=True)

    left = max(cr_df["datetime"].min(), kp_df["datetime"].min())
    right = min(cr_df["datetime"].max(), kp_df["datetime"].max())
    xlim = (pd.to_datetime(left), pd.to_datetime(right))

    x_start = xlim[0].normalize()
    x_end = xlim[1].normalize()
    day_ticks = pd.date_range(x_start, x_end + pd.Timedelta(days=1), freq="2D")
    xlim = (x_start, x_end + pd.Timedelta(days=1) + pd.Timedelta(minutes=1))

    # --- Космические лучи ---
    for i, (ax, station) in enumerate(zip(axes[:-1], stations)):
        ax.plot(cr_df["datetime"], cr_df[station], color="black")
        ax.set_ylabel("Amplitude, %", fontweight="bold")

        (yl, yh), yt = auto_ylim_and_ticks(cr_df[station], target_ticks=5)
        ax.set_ylim(yl, yh)
        ax.set_yticks(yt)

        ax.xaxis.set_major_formatter(formatter)
        ax.set_xlim(xlim[0], xlim[1])
        ax.set_xticks(day_ticks)

        ax.tick_params(axis="x", pad=20, labelbottom=True)
        style_axes(ax)

        ax.set_title(labels[i], loc="left", x=0.0125, y=0.80, weight="bold")

        ax.text(0.98, 0.90, station, transform=ax.transAxes, ha="right", va="top", fontweight="bold")

    # --- Kp ---
    ax_kp = axes[-1]
    plot_kp_bars(ax=ax_kp, kp_df=kp_df, set_xlabel=True)

    ax_kp.xaxis.set_major_formatter(formatter)
    ax_kp.set_xlim(xlim[0], xlim[1])
    ax_kp.set_xticks(day_ticks)
    ax_kp.tick_params(axis="x", pad=20)
    style_axes(ax_kp)
    ax_kp.set_title(labels[-1], loc="left", x=0.0125, y=0.75, weight="bold")


    fig.suptitle(_format_month_title(x_start, x_end), fontsize=30, y=0.995)
    align_ylabels(axes, left_x=-0.055)
    fig.subplots_adjust(hspace=0.5, top=0.97, bottom=0.08, left=0.1, right=0.97)

    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "Cosmic_Ray.png")

    fig.savefig(save_path)
    return fig
