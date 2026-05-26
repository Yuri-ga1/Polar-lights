from __future__ import annotations

import string
from typing import Any, Mapping, Sequence

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import pandas as pd

from app.visualization.plot_constructor_pack.metadata import PlotMetadataBuilder
from app.visualization.plot_constructor_pack.models import ParsedPlot
from app.visualization.plot_constructor_pack.panels import PlotPanelBuilder
from app.visualization.plot_constructor_pack.registry import PlotRegistry
from app.visualization.plot_constructor_pack.renderers import PlotRenderer

try:
    from IPython.display import Markdown, display
except ImportError:
    Markdown = None
    display = None


class PlotConstructor:
    """Build stacked plots from processor outputs using plot names."""

    def __init__(self, processor_results: Mapping[str, Any]) -> None:
        self.processor_results = dict(processor_results)

        self.registry = PlotRegistry(self.processor_results)
        self.metadata_builder = PlotMetadataBuilder(self.processor_results, self.registry)
        self.panel_builder = PlotPanelBuilder()
        self.renderer = PlotRenderer(self.registry, self.processor_results)

    def available_plots(
        self,
        with_details: bool = True,
        as_markdown: bool = True,
    ) -> list[str | dict[str, Any]] | str | None:
        if not as_markdown:
            return self.metadata_builder.available_plots(with_details=with_details)

        markdown_text = self.metadata_builder.available_plots_markdown()

        if display is not None and Markdown is not None:
            display(Markdown(markdown_text))
            return None

        return markdown_text

    @staticmethod
    def _parse_time_markers(raw_time: Any) -> list[pd.Timestamp]:
        if raw_time is None:
            return []

        values = raw_time if isinstance(raw_time, (list, tuple, set)) else [raw_time]
        markers: list[pd.Timestamp] = []

        for value in values:
            ts = pd.to_datetime(value, errors="coerce", utc=True)
            if pd.isna(ts):
                continue

            markers.append(pd.Timestamp(ts))

        return markers
    
    @staticmethod
    def _panel_label(index: int) -> str:
        letters = string.ascii_lowercase
        label = ""

        while True:
            index, remainder = divmod(index, len(letters))
            label = letters[remainder] + label

            if index == 0:
                return label

            index -= 1

    @staticmethod
    def _add_panel_label(ax: plt.Axes, label: str) -> None:
        ax.text(
            0.02,
            0.96,
            label,
            transform=ax.transAxes,
            fontsize=plt.rcParams["font.size"],
            fontweight=plt.rcParams["font.weight"],
            va="top",
            ha="left",
            bbox={
                "boxstyle": "round,pad=0.25",
                "facecolor": "white",
                "edgecolor": "none",
                "alpha": 0.75,
            },
            zorder=100,
        )

    def _collect_map_time_markers(self, parsed: list[ParsedPlot]) -> list[pd.Timestamp]:
        markers: list[pd.Timestamp] = []

        for item in parsed:
            if item.descriptor.plot_type != "map":
                continue

            markers.extend(self._parse_time_markers(item.params.get("time")))

        return markers

    def _parse_plots(
        self,
        plots: Sequence[str | Mapping[str, Any]],
    ) -> list[ParsedPlot]:
        parsed: list[ParsedPlot] = []

        for item in plots:
            if isinstance(item, str):
                name = item
                params: dict[str, Any] = {}

            elif isinstance(item, Mapping):
                name = str(item.get("name", "")).strip()
                params = dict(item.get("params", {}))

            else:
                raise ValueError(f"Unsupported plot spec type: {type(item)!r}")

            if not name:
                raise ValueError("Each plot spec must contain non-empty 'name'.")

            descriptor = self.registry.resolve_descriptor(name)
            data, column = self.registry.extract_plot_data(descriptor)

            parsed.append(
                ParsedPlot(
                    descriptor=descriptor,
                    params=params,
                    data=data,
                    column=column,
                )
            )

        return parsed

    def plot(
        self,
        plots: Sequence[str | Mapping[str, Any]],
        *,
        figsize: tuple[float, float] | None = None,
    ) -> tuple[plt.Figure, list[plt.Axes]]:
        if not plots:
            raise ValueError("plots list is empty.")

        parsed = self._parse_plots(plots)
        time_markers = self._collect_map_time_markers(parsed)
        panels = self.panel_builder.expand(parsed)

        fig = plt.figure(figsize=figsize or (16, 4 * len(panels)))
        outer_grid = fig.add_gridspec(len(panels), 1)

        axes: list[plt.Axes] = []
        label_index = 0

        for idx, panel in enumerate(panels):
            subplot_spec = outer_grid[idx]

            if panel.descriptor.plot_type == "map" and panel.map_times:
                map_axes = self.renderer.plot_map_panel(
                    fig=fig,
                    subplot_spec=subplot_spec,
                    panel=panel,
                )

                for ax in map_axes:
                    self._add_panel_label(
                        ax,
                        self._panel_label(label_index),
                    )
                    label_index += 1

                axes.extend(map_axes)
                continue

            if panel.descriptor.plot_type == "map":
                ax = fig.add_subplot(
                    subplot_spec,
                    projection=ccrs.PlateCarree(),
                )

                if isinstance(panel.data, dict):
                    raise ValueError(
                        f"Map plot '{panel.descriptor.name}' has no selected map times."
                    )

                self.renderer.plot_map_table(
                    ax=ax,
                    descriptor=panel.descriptor,
                    data=panel.data,
                    params=panel.params,
                )

                self._add_panel_label(
                    ax,
                    self._panel_label(label_index),
                )
                label_index += 1

                axes.append(ax)
                continue

            ax = fig.add_subplot(subplot_spec)

            self.renderer.plot_regular_panel(
                ax=ax,
                panel=panel,
                time_markers=time_markers,
            )
            self.renderer.align_ylabels(ax)

            self._add_panel_label(
                ax,
                self._panel_label(label_index),
            )
            label_index += 1

            axes.append(ax)

        fig.tight_layout()
        return fig, axes
