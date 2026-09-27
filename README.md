# Polar lights

## Project Overview
Polar Lights is a data-processing and visualization project for auroral and ionospheric monitoring. The pipeline coordinates multiple workflows (aurora mapping, ROTI, adjusted TEC, and supporting data products) and writes output plots and artifacts for a selected date.

## Installation (Poetry)
1. Install Poetry (if not already installed).
2. Install dependencies:

```bash
poetry install
```

3. Run commands in the Poetry environment with `poetry run ...` or open a shell:

```bash
poetry shell
```

## Backend API

The HTTP backend has a separate entrypoint and optional dependencies:

```bash
poetry install --extras backend
poetry run uvicorn app.backend.api:create_app --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the catalog, availability, data and job APIs.
The backend uses `files/processed/data.csv` and preserves the existing notebook
caches and pipeline interfaces. See [backend setup and API contracts](docs/backend.md)
for Arrow maps, streaming keograms, render jobs, configuration and tests.

## Running the Pipeline
You can run the pipeline from Python by calling the existing entrypoint in `main.py` or by constructing `MainPipelineConfig` and calling `run_main_pipeline`.

Example:

```python
from app.pipeline.main_pipeline import MainPipelineConfig, run_main_pipeline

config = MainPipelineConfig(
    date_str="2024-01-15",
    download_base_dir="files",
    plots_base_dir="results",
    ionosonde_code=None,
    cosmic_station_codes=None,
    simurg_email=None,
)

run_main_pipeline(config)
```

Local data uses one shared store: raw responses are in `files/raw/<source>/`,
normalized tables are in `files/processed/<source>.csv`. SIMuRG map files are
kept unchanged in `files/maps/<product>/`, so their original date/DOY filenames
remain available to the processor. Repeating a supported
space-weather request reuses processed data and downloads only missing ranges.
Generated plots are stored under `results/<date>/`.

For the Aurora Observations map, the source can be selected with
`source="aurorasaurus"` or `source="spaceweatherlive"` in
`run_observation_workflow` (or with `observation_source` in
`MainPipelineConfig`).

SpaceWeatherLive requests use a random 10–20 second delay and up to three
attempts. Failed dates or observation pages are reported and skipped so the
remaining workflow can continue.

## Notebook Usage
Use the notebook at `notebooks/00_examples_and_run.ipynb` as the visual entry point.

- **Section 1 — Examples (precomputed results):**
  Displays committed reference plots only (no pipeline execution).
- **Section 2 — Run with your parameters:**
  Lets you set `date_str`, optional station/email parameters, run the real pipeline, and show generated PNG outputs inline.

Reference examples are stored in:

- `notebooks/graph_examples/` (committed gallery assets)

Runtime-generated outputs are stored in:

- `results/`

Downloaded source files are stored under `files/raw/`; processed tables and
multidimensional maps are stored under `files/processed/` and `files/maps/`.

## SDO/HMI solar disk with NOAA active regions

```bash
poetry install
poetry run python -m app.pipeline.solar_disk_pipeline --date 2026-01-20 --time 12:00:00
```

This downloads the nearest Helioviewer HMI continuum JP2 and the historical NOAA
Solar Region Summary, rotates region coordinates to the HMI WCS epoch, and saves
an annotated PNG plus source/coordinate metadata in `results/2026-01-20/`.
Subsequent runs use the file cache; `--force-download` refreshes it.

```python
from app.pipeline.solar_disk_pipeline import SolarDiskConfig, build_solar_disk

fig, ax = build_solar_disk(SolarDiskConfig(requested_time="2026-01-20T12:00:00Z"))
```

See [the solar disk section in the main notebook](notebooks/00_examples_and_run.ipynb) for multiple dates and
`PlotConstructor` integration, and [source and coordinate details](docs/solar_disk.md)
for the scientific conventions, configuration, and control-run verification.

To render every available ROTI or adjusted TEC map from a notebook, stream the
SIMuRG slices into `plot_all_maps`. The helper splits output into several PNG
files instead of trying to place the whole time range into one oversized figure.

```python
from app.simurg.simurg_processor import DataProduct, SimurgProcessor
from app.visualization.roti_plotter import plot_all_maps

processor = SimurgProcessor(folder_path="files/2025-04-16/simurg")

output_dir = plot_all_maps(
    data=processor.iter_slices("2025-04-16", product_type=DataProduct.TEC_ADJUSTED),
    product_type="tec_adjusted",
    save_dir="results/2025-04-16",
    maps_per_figure=4,
    show_noon_line=True,
    terminator_height_km=0,
)
```

For `PlotConstructor`, use `time="all"` or `plot_all_times=True` in map params.

## Run in Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Yuri-ga1/Polar-lights/blob/main/notebooks/00_examples_and_run.ipynb)

> После открытия в Colab: **File → Save a copy in Drive**, чтобы получить свою копию и спокойно редактировать.
