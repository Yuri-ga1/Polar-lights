import os
os.environ["MPLBACKEND"] = "Agg"

from app.logging_config import configure_logging

from app.pipeline.main_pipeline import MainPipelineConfig, run_main_pipeline
from app.visualization.plot_settings import set_plt_def_params

def main(
    date_str: str,
    download_base_dir: str = "files",
    plots_base_dir: str = "results",
    ionosonde_code: str | None = None,
    cosmic_station_codes: list[str] | None = None,
    email: str | None = None,
) -> None:
    configure_logging()
    set_plt_def_params()

    config = MainPipelineConfig(
        date_str=date_str,
        download_base_dir=download_base_dir,
        plots_base_dir=plots_base_dir,
        ionosonde_code=ionosonde_code,
        cosmic_station_codes=cosmic_station_codes,
        simurg_email=email,
    )
    run_main_pipeline(config)


if __name__ == "__main__":
    date = '2026-01-20'
    ionosonde_code = None
    cosmic_stations = None
    email = None

    main(
        date_str=date,
        download_base_dir="files",
        plots_base_dir="results",
        ionosonde_code=ionosonde_code,
        cosmic_station_codes=cosmic_stations,
        email=email,
    )
