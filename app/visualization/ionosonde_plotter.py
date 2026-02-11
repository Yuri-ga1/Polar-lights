import os

import pandas as pd
import matplotlib.pyplot as plt

from app.visualization.plot_utils import auto_ylim_and_ticks, panel_labels, style_axes


def plot_ionosonde(df: pd.DataFrame) -> str:
    """
    Строит графики:
    ΔfoF2 (MHz)
    ΔfoF2 (%)
    ΔhmF2 (km)
    """
    fig, axes = plt.subplots(
        nrows=3,
        ncols=1,
        figsize=(18, 12),
        sharex=True,
    )

    dt = pd.to_datetime(df["datetime"], errors="coerce")
    x = (dt.dt.hour + dt.dt.minute / 60.0).reset_index(drop=True)

    series = [
        ("dfoF2", "ΔfoF2, MHz"),
        ("dfoF2p", "ΔfoF2, %"),
        ("dhmF2", "ΔhmF2, km"),
    ]

    panel_letters = panel_labels(len(axes))

    for i, (ax, (col, ylabel)) in enumerate(zip(axes, series)):
        y = pd.to_numeric(df[col], errors="coerce").reset_index(drop=True)

        ax.plot(x, y, color="black")

        y_nonan = y.dropna()
        if y_nonan.empty:
            ax.set_ylabel(ylabel, fontweight="bold")
            style_axes(ax)
            ax.set_title(panel_letters[i], loc="left", x=0.0125, y=0.8, weight="bold")
            ax.tick_params(axis="x", labelbottom=True, pad=20)
            continue

        idx_max = y_nonan.idxmax()
        idx_min = y_nonan.idxmin()

        ax.scatter(x.iloc[idx_max], y.iloc[idx_max], color="red", s=175, zorder=5)
        ax.scatter(x.iloc[idx_min], y.iloc[idx_min], color="blue", s=175, zorder=5)

        (yl0, yl1), yticks = auto_ylim_and_ticks(y_nonan)
        ax.set_ylim(yl0, yl1)
        ax.set_yticks(yticks)

        ax.set_ylabel(ylabel, fontweight="bold")
        style_axes(ax)

        ax.set_title(panel_letters[i], loc="left", x=0.0125, y=0.8, weight="bold")
        ax.tick_params(axis="x", labelbottom=True, pad=20)

    for ax in axes:
        ax.set_xlim(0, 24)
        ax.set_xticks(list(range(0, 25, 3)))

    axes[-1].set_xlabel("Time, UT", fontweight="bold")

    fig.subplots_adjust(hspace=0.5, top=0.97, bottom=0.1, left=0.08, right=0.97)

    save_dir = os.path.join("files", "graphs")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "ionosonde.png")

    fig.savefig(save_path)
    plt.close(fig)
    return save_path
