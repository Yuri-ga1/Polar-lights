import os
import math
import pandas as pd
import matplotlib.pyplot as plt

def panel_labels(n: int) -> list[str]:
    """
    Returns a list of panel labels: a, b, c, ... (n items).
    """
    if n < 0:
        raise ValueError("n must be non-negative")

    alphabet = "abcdefghijklmnopqrstuvwxyz"
    if n > len(alphabet):
        raise ValueError(f"n must be <= {len(alphabet)}")

    return list(alphabet[:n])


def _nice_step(y_range: float) -> float:
    """Pick a 'nice' tick step based on data range."""
    if y_range <= 0 or math.isnan(y_range):
        return 1.0
    # Aim for ~4-6 intervals
    raw = y_range / 5.0
    magnitude = 10 ** math.floor(math.log10(raw))
    norm = raw / magnitude
    if norm <= 1:
        step = 1
    elif norm <= 2:
        step = 2
    elif norm <= 2.5:
        step = 2.5
    elif norm <= 5:
        step = 5
    else:
        step = 10
    return step * magnitude


def _auto_ylim_and_ticks(y: pd.Series, target_ticks: int = 5):
    """Automatic limits and ticks (publication-ish) without per-file tweaking."""
    y = y.dropna()
    if y.empty:
        return (-1, 1), [-1, 0, 1]

    ymin = float(y.min())
    ymax = float(y.max())

    # If flat series
    if math.isclose(ymin, ymax):
        pad = 1.0 if ymin == 0 else abs(ymin) * 0.2
        lo, hi = ymin - pad, ymax + pad
        step = _nice_step(hi - lo)
    else:
        # Add padding
        pad = 0.08 * (ymax - ymin)
        lo, hi = ymin - pad, ymax + pad
        step = _nice_step(hi - lo)

    # Snap to step grid
    lo_snapped = math.floor(lo / step) * step
    hi_snapped = math.ceil(hi / step) * step

    # Build ticks
    ticks = []
    t = lo_snapped
    # guard against infinite loops
    for _ in range(500):
        if t > hi_snapped + 1e-12:
            break
        ticks.append(t)
        t += step

    # If too many ticks, increase step
    while len(ticks) > 8:
        step *= 2
        lo_snapped = math.floor(lo / step) * step
        hi_snapped = math.ceil(hi / step) * step
        ticks = []
        t = lo_snapped
        for _ in range(500):
            if t > hi_snapped + 1e-12:
                break
            ticks.append(t)
            t += step

    return (lo_snapped, hi_snapped), ticks


def plot_ionosonde(df: pd.DataFrame):
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
        figsize=(18, 12),   # как в первом
        sharex=True
    )

    x = df["UT"]

    series = [
        ("dfoF2",  "ΔfoF2, MHz"),
        ("dfoF2p", "ΔfoF2, %"),
        ("dhmF2",  "ΔhmF2, km"),
    ]

    panel_letters = panel_labels(len(axes))

    for i, (ax, (col, ylabel)) in enumerate(zip(axes, series)):
        y = df[col]

        ax.plot(x, y, color="black")

        idx_max = y.idxmax()
        idx_min = y.idxmin()

        ax.scatter(x.loc[idx_max], y.loc[idx_max], color="red",  s=175, zorder=5)
        ax.scatter(x.loc[idx_min], y.loc[idx_min], color="blue", s=175, zorder=5)

        (yl0, yl1), yticks = _auto_ylim_and_ticks(y)
        ax.set_ylim(yl0, yl1)
        ax.set_yticks(yticks)

        # подписи/стиль как в первом
        ax.set_ylabel(ylabel, fontweight="bold")
        ax.grid(True)

        # серые рамки
        for spine in ax.spines.values():
            spine.set_color("gray")

        # буквы a/b/c слева
        ax.set_title(panel_letters[i], loc="left", x=0.0125, y=0.8, weight="bold")

        # показываем подписи x на всех (как в первом)
        ax.tick_params(axis="x", labelbottom=True, pad=20)

    # X как в первом
    for ax in axes:
        ax.set_xlim(0, 24)
        ax.set_xticks(list(range(0, 25, 3)))

    axes[-1].set_xlabel("Time, UT", fontweight="bold")

    # расстояния как в первом
    fig.subplots_adjust(hspace=0.5, top=0.97, bottom=0.1, left=0.08, right=0.97)

    save_dir = os.path.join("files", "graphs")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "ionosonde.png")

    fig.savefig(save_path)   # важно: сохраняем FIG, а не ax
    plt.close(fig)
    return save_path
