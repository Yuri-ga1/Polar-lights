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
