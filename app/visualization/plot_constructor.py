from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PlotRequest = str | Mapping[str, Any]

MAP_PLOT_NAMES = {
    "roti",
    "gim",
    "adjusted tec",
    "adjusted_tec",
    "keogram",
    "aurora observation",
    "aurora",
}
HISTOGRAM_PLOT_NAMES = {"kp"}


@dataclass(frozen=True)
class PlotDefinition:
    """Resolved plot metadata used by PlotConstructor."""

    name: str
    canonical_name: str
    data: Any
    plot_type: str
    source: str


class PlotConstructor:
    """Stacked plotting constructor for processor results.

    Parameters
    ----------
    processor_results:
        Aggregated results returned by Processor classes.
        Usually dict-like: ``{"omni": df, "kp": df, "ROTI": map_dict, ...}``.
    """

    def __init__(self, processor_results: Mapping[str, Any]):
        self.processor_results: dict[str, Any] = dict(processor_results)
        self._definitions = self._build_registry(self.processor_results)

    def available_plots(self) -> list[str]:
        """Return available plot names discovered from processor outputs."""
        return sorted(self._definitions.keys(), key=str.lower)

    def plot(
        self,
        plot_requests: Sequence[PlotRequest],
        *,
        figsize: tuple[int, int] = (16, 4),
        sharex: bool = False,
    ) -> tuple[plt.Figure, list[plt.Axes]]:
        """Build requested plots in a vertical stack.

        ``plot_requests`` accepts strings or mappings like
        ``{"name": "Dst", "params": {"color": "black"}}``.
        """
        if not plot_requests:
            raise ValueError("plot_requests is empty.")

        resolved: list[tuple[PlotDefinition, dict[str, Any]]] = []
        for item in plot_requests:
            name, params = self._normalize_request(item)
            definition = self._resolve_plot(name)
            resolved.append((definition, params))

        fig_h = max(figsize[1] * len(resolved), 4)
        fig, axes_raw = plt.subplots(
            nrows=len(resolved),
            ncols=1,
            figsize=(figsize[0], fig_h),
            sharex=sharex,
            subplot_kw=None,
        )

        axes = [axes_raw] if len(resolved) == 1 else list(axes_raw)

        for idx, (ax, (definition, params)) in enumerate(zip(axes, resolved), start=1):
            plot_type = definition.plot_type or "timeseries"
            if plot_type == "map":
                # Replace regular axis with geo axis for this subplot slot.
                geo_ax = fig.add_subplot(len(resolved), 1, idx, projection=ccrs.PlateCarree())
                ax.remove()
                axes[idx - 1] = geo_ax
                self._plot_map(geo_ax, definition, params)
            elif plot_type == "histogram":
                self._plot_histogram(ax, definition, params)
            else:
                self._plot_timeseries(ax, definition, params)

        fig.tight_layout()
        return fig, axes

    @staticmethod
    def _normalize_request(item: PlotRequest) -> tuple[str, dict[str, Any]]:
        if isinstance(item, str):
            return item, {}
        if not isinstance(item, Mapping) or "name" not in item:
            raise ValueError(f"Plot request must be str or mapping with 'name'. Got: {item!r}")
        return str(item["name"]), dict(item.get("params", {}))

    def _resolve_plot(self, requested_name: str) -> PlotDefinition:
        key = requested_name.strip().lower()
        if key in self._definitions:
            return self._definitions[key]

        available = ", ".join(self.available_plots())
        raise ValueError(
            f"Unknown plot '{requested_name}'. Available plots: {available}"
        )

    def _build_registry(self, results: Mapping[str, Any]) -> dict[str, PlotDefinition]:
        registry: dict[str, PlotDefinition] = {}

        for source_name, payload in results.items():
            canonical_source = str(source_name).strip()
            self._register_name(registry, canonical_source, payload, canonical_source)

            if isinstance(payload, pd.DataFrame):
                for col in payload.columns:
                    if str(col).lower() in {"datetime", "date", "time", "hour", "year", "month", "day", "doy", "mn", "hr"}:
                        continue
                    self._register_name(registry, str(col), payload, canonical_source)

        # Helpful aliases for known products.
        alias_map = {
            "aurora observation": ["aurora", "aurora observations", "observation"],
            "adjusted tec": ["tec adjusted", "adjusted_tec"],
        }
        for canonical, aliases in alias_map.items():
            if canonical in registry:
                for alias in aliases:
                    registry.setdefault(alias, registry[canonical])

        return registry

    def _register_name(
        self,
        registry: dict[str, PlotDefinition],
        raw_name: str,
        payload: Any,
        source_name: str,
    ) -> None:
        key = raw_name.strip().lower()
        if not key or key in registry:
            return

        plot_type = self._infer_plot_type(key)
        registry[key] = PlotDefinition(
            name=raw_name,
            canonical_name=key,
            data=payload,
            plot_type=plot_type,
            source=source_name,
        )

    @staticmethod
    def _infer_plot_type(name: str) -> str:
        if name in MAP_PLOT_NAMES:
            return "map"
        if name in HISTOGRAM_PLOT_NAMES:
            return "histogram"
        return "timeseries"

    @staticmethod
    def _extract_x(df: pd.DataFrame) -> pd.Series:
        for candidate in ("datetime", "DateTime", "date", "time"):
            if candidate in df.columns:
                return pd.to_datetime(df[candidate], errors="coerce")
        if isinstance(df.index, pd.DatetimeIndex):
            return pd.Series(df.index)
        return pd.Series(np.arange(len(df)))

    def _plot_timeseries(self, ax: plt.Axes, definition: PlotDefinition, params: dict[str, Any]) -> None:
        data = definition.data
        color = params.pop("color", None)

        if isinstance(data, pd.DataFrame):
            col = definition.name if definition.name in data.columns else definition.canonical_name
            if col not in data.columns:
                # fallback: first numeric column
                numeric_cols = data.select_dtypes(include="number").columns.tolist()
                if not numeric_cols:
                    raise ValueError(f"No numeric columns to plot for '{definition.name}'.")
                col = numeric_cols[0]
            x = self._extract_x(data)
            y = pd.to_numeric(data[col], errors="coerce")
            ax.plot(x, y, color=color, **params)
            ax.set_ylabel(col)
        elif isinstance(data, pd.Series):
            ax.plot(data.index, data.values, color=color, **params)
            ax.set_ylabel(definition.name)
        else:
            raise ValueError(f"Timeseries plot '{definition.name}' has unsupported data type: {type(data).__name__}")

        ax.set_title(definition.name)
        ax.grid(True, linestyle="--", alpha=0.35)

    def _plot_histogram(self, ax: plt.Axes, definition: PlotDefinition, params: dict[str, Any]) -> None:
        data = definition.data
        if not isinstance(data, pd.DataFrame):
            raise ValueError(f"Histogram '{definition.name}' expects DataFrame, got {type(data).__name__}")

        col = definition.name if definition.name in data.columns else definition.canonical_name
        if col not in data.columns:
            raise ValueError(f"Column '{definition.name}' not found in source '{definition.source}'.")

        values = pd.to_numeric(data[col], errors="coerce").dropna()
        bins = params.pop("bins", 9)
        color = params.pop("color", "tab:blue")
        ax.hist(values, bins=bins, color=color, edgecolor="black", **params)
        ax.set_title(definition.name)
        ax.set_ylabel("count")
        ax.set_xlabel(col)
        ax.grid(True, axis="y", linestyle="--", alpha=0.35)

    def _plot_map(self, ax: plt.Axes, definition: PlotDefinition, params: dict[str, Any]) -> None:
        data = definition.data
        cmap = params.pop("cmap", "jet")
        ax.set_global()
        ax.add_feature(cfeature.LAND, facecolor="lightgray")
        ax.add_feature(cfeature.OCEAN, facecolor="white")
        ax.add_feature(cfeature.COASTLINE, linewidth=0.6)

        if isinstance(data, dict):
            if not data:
                raise ValueError(f"No data for map '{definition.name}'.")
            requested_time = params.pop("plot_time", None)
            if requested_time is None:
                t = sorted(data.keys())[0]
            else:
                t = pd.to_datetime(requested_time).to_pydatetime()
            if t not in data:
                available = ", ".join(str(k) for k in sorted(data.keys())[:5])
                raise ValueError(f"Missing plot_time '{t}' for '{definition.name}'. Example times: {available}")

            arr = data[t]
            names = getattr(getattr(arr, "dtype", None), "names", None)
            if not names or not {"lat", "lon", "vals"}.issubset(set(names)):
                raise ValueError(f"Map '{definition.name}' expects structured array with lat/lon/vals fields.")
            img = ax.scatter(arr["lon"], arr["lat"], c=arr["vals"], s=params.pop("s", 8), cmap=cmap, transform=ccrs.PlateCarree(), **params)
            plt.colorbar(img, ax=ax, shrink=0.75, pad=0.02)
            ax.set_title(f"{definition.name}: {t}")
            return

        if isinstance(data, pd.DataFrame):
            required = {"lat", "lon"}
            if not required.issubset(set(data.columns)):
                raise ValueError(f"Map '{definition.name}' expects columns {sorted(required)} in DataFrame.")
            color_col = params.pop("color_col", "duration_min" if "duration_min" in data.columns else None)
            colors = data[color_col] if color_col and color_col in data.columns else "tab:red"
            img = ax.scatter(data["lon"], data["lat"], c=colors, cmap=cmap if isinstance(colors, pd.Series) else None, s=params.pop("s", 20), transform=ccrs.PlateCarree(), **params)
            if isinstance(colors, pd.Series):
                plt.colorbar(img, ax=ax, shrink=0.75, pad=0.02)
            ax.set_title(definition.name)
            return

        raise ValueError(f"Map plot '{definition.name}' has unsupported data type: {type(data).__name__}")
