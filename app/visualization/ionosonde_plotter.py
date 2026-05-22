import os

import pandas as pd
import matplotlib.pyplot as plt

from app.visualization.plot_utils import auto_ylim_and_ticks, panel_labels, style_axes, align_ylabels
from app.visualization.geo_utils import format_geo_coord


def format_ionosonde_title(df: pd.DataFrame, value_label: str | None = None) -> str:
    station_code = df.attrs.get("station_code")
    station_name = df.attrs.get("station_name")
    station_lat = df.attrs.get("station_lat")
    station_lon = df.attrs.get("station_lon")

    title = f"Ionosonde {station_code}" if station_code else "Ionosonde"

    if station_name:
        title += f" {station_name}"

    if station_lat is not None and station_lon is not None:
        lat_text = format_geo_coord(float(station_lat), "lat")
        lon_text = format_geo_coord(float(station_lon), "lon")
        title += f" ({lat_text}, {lon_text})"

    if value_label:
        title += f": {value_label}"

    return title


def plot_ionosonde_series_on_ax(
    ax: plt.Axes,
    df: pd.DataFrame,
    *,
    time_col: str,
    value_col: str,
    value_label: str | None = None,
    x_as_hours: bool = False,
    color: str = "black",
    linewidth: float = 1.5,
    ylabel: str | None = None,
    show_min: bool = True,
    show_max: bool = True,
    show_extrema: bool | None = None,
) -> None:
    if df is None or df.empty:
        raise ValueError("Ionosonde DataFrame is empty")

    if time_col not in df.columns or value_col not in df.columns:
        raise ValueError(
            f"Ionosonde DataFrame must contain '{time_col}' and '{value_col}'"
        )

    if show_extrema is not None:
        show_min = show_extrema
        show_max = show_extrema

    data = df.copy()
    data[time_col] = pd.to_datetime(data[time_col], errors="coerce")
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce")
    data = data.dropna(subset=[time_col, value_col]).reset_index(drop=True)

    if data.empty:
        raise ValueError(f"Ionosonde column '{value_col}' has no valid values")

    if x_as_hours:
        x = data[time_col].dt.hour + data[time_col].dt.minute / 60.0
    else:
        x = data[time_col]

    y = data[value_col]

    label = value_label or value_col

    ax.plot(
        x,
        y,
        color=color,
        linewidth=linewidth,
    )

    if show_min:
        min_idx = y.idxmin()
        ax.scatter(
            x.iloc[min_idx],
            y.iloc[min_idx],
            color="blue",
            marker="v",
            s=90,
            zorder=5,
            label=f"min = {y.iloc[min_idx]:.2f}",
        )

    if show_max:
        max_idx = y.idxmax()
        ax.scatter(
            x.iloc[max_idx],
            y.iloc[max_idx],
            color="red",
            marker="^",
            s=90,
            zorder=5,
            label=f"max = {y.iloc[max_idx]:.2f}",
        )

    y_nonan = y.dropna()
    if not y_nonan.empty:
        (yl0, yl1), yticks = auto_ylim_and_ticks(y_nonan)
        ax.set_ylim(yl0, yl1)
        ax.set_yticks(yticks)

    ax.set_ylabel(ylabel or label, fontweight="bold")
    style_axes(ax)

    if show_min or show_max:
        ax.legend(loc='upper right')


def plot_ionosonde(
    df: pd.DataFrame,
    save_dir: str = os.path.join("files", "graphs"),
    *,
    show_min: bool = True,
    show_max: bool = True,
    show_extrema: bool | None = None,
) -> str:
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

    series = [
        ("dfoF2", "ΔfoF2, MHz"),
        ("dfoF2p", "ΔfoF2, %"),
        ("dhmF2", "ΔhmF2, km"),
    ]

    panel_letters = panel_labels(len(axes))

    for i, (ax, (col, ylabel)) in enumerate(zip(axes, series)):
        plot_ionosonde_series_on_ax(
            ax,
            df,
            time_col="datetime",
            value_col=col,
            value_label=ylabel,
            x_as_hours=True,
            color="black",
            ylabel=ylabel,
            show_min=show_min,
            show_max=show_max,
            show_extrema=show_extrema,
        )

        ax.set_title(panel_letters[i], loc="left", x=0.0125, y=0.8, weight="bold")
        ax.tick_params(axis="x", labelbottom=True, pad=20)

    for ax in axes:
        ax.set_xlim(0, 24)
        ax.set_xticks(list(range(0, 25, 3)))

    axes[-1].set_xlabel("Time, UT", fontweight="bold")

    fig.suptitle(format_ionosonde_title(df), fontweight="bold")
    align_ylabels(axes, left_x=-0.075, right_x=1.07)
    fig.subplots_adjust(hspace=0.5, top=0.92, bottom=0.1, left=0.08, right=0.97)

    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "ionosonde.png")

    fig.savefig(save_path)

    return fig