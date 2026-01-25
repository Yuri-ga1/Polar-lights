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
    Оформление как в первом примере, но всё авто-подстраивается под данные.
    """
    df = df.sort_values("UT").reset_index(drop=True)

    fig, axes = plt.subplots(
        nrows=3,
        ncols=1,
        figsize=(18, 12),
        sharex=True,
    )

    x = df["UT"]

    series = [
        ("dfoF2", "ΔfoF2, MHz"),
        ("dfoF2p", "ΔfoF2, %"),
        ("dhmF2", "ΔhmF2, km"),
    ]

    panel_letters = panel_labels(len(axes))

    for i, (ax, (col, ylabel)) in enumerate(zip(axes, series)):
        y = df[col]

        ax.plot(x, y, color="black")

        idx_max = y.idxmax()
        idx_min = y.idxmin()

        ax.scatter(x.loc[idx_max], y.loc[idx_max], color="red", s=175, zorder=5)
        ax.scatter(x.loc[idx_min], y.loc[idx_min], color="blue", s=175, zorder=5)

        (yl0, yl1), yticks = auto_ylim_and_ticks(y)
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
