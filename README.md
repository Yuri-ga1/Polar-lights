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

Downloaded source files are stored under `files/<date>/`.
Generated plots are stored under `results/<date>/`.

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

Downloaded data files are stored in:

- `files/`

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
