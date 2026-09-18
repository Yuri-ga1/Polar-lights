"""Programmatic API and CLI for annotated HMI continuum disks."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence

import matplotlib.pyplot as plt

from app.solar.models import SolarDiskConfig
from app.solar.solar_processor import SolarProcessor
from app.visualization.solar_disk_plotter import plot_solar_disk_on_ax

__all__ = [
    "SolarDiskConfig",
    "build_solar_disk",
    "build_solar_disks",
    "prepare_solar_disk",
]


def prepare_solar_disk(config: SolarDiskConfig):
    """Download/cache and process a typed product, also accepted by PlotConstructor."""
    return SolarProcessor(config.cache_dir).load(config)


def _save(fig, configs, datasets):
    config = configs[0]
    if not config.save:
        return
    path = config.output_path
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=config.dpi, facecolor=fig.get_facecolor())
    metadata = (
        datasets[0].metadata
        if len(datasets) == 1
        else {"panels": [data.metadata for data in datasets]}
    )
    config.metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logging.getLogger(__name__).info("Saved %s", path)


def build_solar_disks(configs: Sequence[SolarDiskConfig]):
    """Build 1 × N disks. First config sets output file/dpi; figsize is per panel."""
    if not configs:
        raise ValueError("Provide at least one SolarDiskConfig")
    datasets = [prepare_solar_disk(config) for config in configs]
    fig = plt.figure(
        figsize=(
            sum(config.figsize[0] for config in configs),
            max(config.figsize[1] for config in configs),
        ),
        layout="constrained",
    )
    axes = []
    for index, data in enumerate(datasets):
        ax = fig.add_subplot(1, len(datasets), index + 1, projection=data.solar_map)
        plot_solar_disk_on_ax(ax, data)
        axes.append(ax)
    _save(fig, configs, datasets)
    return fig, axes


def build_solar_disk(config: SolarDiskConfig):
    """Return (Figure, WCSAxes), optionally saving PNG and a provenance JSON."""
    fig, axes = build_solar_disks([config])
    return fig, axes[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-01-20", help="UTC date, YYYY-MM-DD")
    parser.add_argument("--time", default="12:00:00", help="UTC time, HH:MM[:SS]")
    parser.add_argument("--max-time-delta-minutes", type=float, default=30)
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--no-annotations", action="store_true")
    parser.add_argument("--no-srs-fallback", action="store_true")
    parser.add_argument("--colorbar", action="store_true")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--figsize", type=float, nargs=2, default=(9, 9))
    parser.add_argument("--download-base-dir", default="files")
    parser.add_argument("--plots-base-dir", default="results")
    parser.add_argument("--filename")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config = SolarDiskConfig(
        requested_time=f"{args.date}T{args.time}Z",
        max_time_delta_minutes=args.max_time_delta_minutes,
        force_download=args.force_download,
        annotate_active_regions=not args.no_annotations,
        allow_srs_fallback=not args.no_srs_fallback,
        colorbar=args.colorbar,
        dpi=args.dpi,
        figsize=tuple(args.figsize),
        download_base_dir=args.download_base_dir,
        plots_base_dir=args.plots_base_dir,
        filename=args.filename,
    )
    fig, _ = build_solar_disk(config)
    plt.close(fig)
    print(config.output_path)


if __name__ == "__main__":
    main()
