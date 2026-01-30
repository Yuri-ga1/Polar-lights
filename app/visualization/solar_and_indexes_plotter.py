import os
from typing import Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.dates import DateFormatter

from app.visualization.plot_utils import *

__all__ = {
    'plot_sw_symh_dst_kp'
}


def _common_xlim_and_ticks(
    *dfs: pd.DataFrame,
    tick_freq: str = "2D",
) -> Tuple[tuple[pd.Timestamp, pd.Timestamp], pd.DatetimeIndex, DateFormatter]:
    """
    Build common x-limits from intersection of all dfs ranges.
    """
    left = max(df["datetime"].min() for df in dfs)
    right = min(df["datetime"].max() for df in dfs)

    x_start = pd.to_datetime(left).normalize()
    x_end = pd.to_datetime(right).normalize()

    day_ticks = pd.date_range(x_start, x_end + pd.Timedelta(days=1), freq=tick_freq)
    xlim = (x_start, x_end + pd.Timedelta(days=1) + pd.Timedelta(minutes=1))

    return xlim, day_ticks, DateFormatter("%d")


def _style_x(ax: plt.Axes, xlim, day_ticks, formatter, show_xlabel: bool = False) -> None:
    ax.set_xlim(*xlim)
    ax.set_xticks(day_ticks)
    ax.xaxis.set_major_formatter(formatter)
    ax.tick_params(axis="x", pad=20, labelbottom=True)
    if show_xlabel:
        ax.set_xlabel("Day", fontweight="bold")
    style_axes(ax)


def _plot_twin_auto(
    ax: plt.Axes,
    x: pd.Series,
    y_left: pd.Series,
    y_right: pd.Series,
    *,
    left_ylabel: str,
    right_ylabel: str,
    left_color: str = "r",
    right_color: str = "k",
    target_ticks: int = 5,
    legend_loc: str = "upper right",
) -> None:
    """
    Twin-y plot with auto ylim/ticks on both axes.
    """
    # left
    l1 = ax.plot(x, y_left, color=left_color, label=left_ylabel)
    ax.set_ylabel(left_ylabel, fontweight="bold")
    ax.yaxis.label.set_color(left_color)
    ax.tick_params(axis="y", colors=left_color)
    ax.spines["left"].set_color(left_color)

    (yl, yh), yt = auto_ylim_and_ticks(y_left, target_ticks=target_ticks)
    ax.set_ylim(yl, yh)
    ax.set_yticks(yt)

    # right
    ax_r = ax.twinx()
    l2 = ax_r.plot(x, y_right, color=right_color, label=right_ylabel)
    ax_r.set_ylabel(right_ylabel, fontweight="bold")

    (yl_r, yh_r), yt_r = auto_ylim_and_ticks(y_right, target_ticks=target_ticks)
    ax_r.set_ylim(yl_r, yh_r)
    ax_r.set_yticks(yt_r)

    ax_r.spines["top"].set_visible(False)
    ax_r.spines["left"].set_visible(False)

    ax.legend(handles=l2 + l1, loc=legend_loc, fontsize=24)


def plot_sw_symh_dst_kp(
    sw_df: pd.DataFrame,
    dst_df: pd.DataFrame,
    kp_df: pd.DataFrame,
):
    labels = panel_labels(4)

    # приведение datetime (на случай строк)
    sw_df = sw_df.copy()
    dst_df = dst_df.copy()
    kp_df = kp_df.copy()
    sw_df["datetime"] = pd.to_datetime(sw_df["datetime"])
    dst_df["datetime"] = pd.to_datetime(dst_df["datetime"])
    kp_df["datetime"] = pd.to_datetime(kp_df["datetime"])

    # общий диапазон времени по пересечению
    xlim, day_ticks, formatter = _common_xlim_and_ticks(sw_df, dst_df, kp_df, tick_freq="2D")

    fig, axes = plt.subplots(4, 1, figsize=(18, 18), sharex=True)

    # --- a) Flow pressure + Speed ---
    ax = axes[0]
    _plot_twin_auto(
        ax=ax,
        x=sw_df["datetime"],
        y_left=sw_df["flow pressure"],
        y_right=sw_df["speed"],
        left_ylabel="Flow pressure, nPa",
        right_ylabel=r"$\mathdefault{Vsw,\; \frac{km}{s}}$",
        left_color="r",
        right_color="k",
        target_ticks=5,
        legend_loc="upper right",
    )
    _style_x(ax, xlim, day_ticks, formatter)
    ax.set_title(labels[0], loc="left", x=0.0125, y=0.80, weight="bold")

    # --- b) IMF: |B| and Bz ---
    ax = axes[1]
    b_abs = np.sqrt(sw_df["bx"] ** 2 + sw_df["by"] ** 2 + sw_df["bz"] ** 2)

    ax.plot(sw_df["datetime"], b_abs, color="k", label="|B|")
    ax.plot(sw_df["datetime"], sw_df["bz"], color="r", label="Bz")
    ax.set_ylabel("IMF, nT", fontweight="bold")

    (yl, yh), yt = auto_ylim_and_ticks(pd.concat([b_abs, sw_df["bz"]]), target_ticks=5)
    ax.set_ylim(yl, yh)
    ax.set_yticks(yt)

    ax.legend(loc="lower right", fontsize=24)
    _style_x(ax, xlim, day_ticks, formatter)
    ax.set_title(labels[1], loc="left", x=0.0125, y=0.80, weight="bold")

    # --- c) SYM-H + Dst ---
    ax = axes[2]
    ax.plot(sw_df["datetime"], sw_df["symh"], color="r", label="SYM-H")
    ax.set_ylabel("SYM-H, nT", fontweight="bold")
    ax.yaxis.label.set_color("r")
    ax.tick_params(axis="y", colors="r")
    ax.spines["left"].set_color("r")

    (yl, yh), yt = auto_ylim_and_ticks(sw_df["symh"], target_ticks=5)
    ax.set_ylim(yl, yh)
    ax.set_yticks(yt)

    ax_r = ax.twinx()
    ax_r.plot(dst_df["datetime"], dst_df["dst"], color="k", label="Dst")

    (yl_r, yh_r), yt_r = auto_ylim_and_ticks(dst_df["dst"], target_ticks=5)
    ax_r.set_ylim(yl_r, yh_r)
    ax_r.set_yticks(yt_r)

    ax_r.spines["top"].set_visible(False)
    ax_r.spines["left"].set_visible(False)

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax_r.get_legend_handles_labels()
    ax.legend(h2 + h1, l2 + l1, loc="lower right", fontsize=24)

    _style_x(ax, xlim, day_ticks, formatter)
    ax.set_title(labels[2], loc="left", x=0.0125, y=0.80, weight="bold")

    # --- d) Kp (как в CR) ---
    ax = axes[3]
    colors = kp_colors(kp_df["kp"])
    ax.bar(kp_df["datetime"], kp_df["kp"], color=colors, width=0.115)

    ax.set_ylabel("Kp", fontweight="bold")
    ax.set_xlabel("Day", fontweight="bold")

    (yl, yh), yt = auto_ylim_and_ticks(kp_df["kp"], target_ticks=4)
    ax.set_ylim(max(0, yl), yh)
    ax.set_yticks(yt)

    _style_x(ax, xlim, day_ticks, formatter, show_xlabel=True)
    ax.set_title(labels[3], loc="left", x=0.0125, y=0.75, weight="bold")

    # layout + save
    fig.subplots_adjust(hspace=0.5, top=0.97, bottom=0.08, left=0.08, right=0.97)

    save_dir = os.path.join("files", "graphs")
    os.makedirs(save_dir, exist_ok=True)

    save_name = "SW_SYMH_DST_KP.png"
    fig.savefig(os.path.join(save_dir, save_name))
    
    plt.close(fig)
