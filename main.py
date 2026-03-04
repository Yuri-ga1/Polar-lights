import os
os.environ["MPLBACKEND"] = "Agg"

import logging

from app.pipeline.main_pipeline import MainPipelineConfig, run_main_pipeline
from app.visualization.plot_settings import set_plt_def_params

def main(
    date_str: str,
    ionosonde_code: str | None = None,
    cosmic_station_codes: list[str] | None = None,
    email: str | None = None,
) -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(threadName)s: %(message)s")
    set_plt_def_params()

    config = MainPipelineConfig(
        date_str=date_str,
        ionosonde_code=ionosonde_code,
        cosmic_station_codes=cosmic_station_codes,
        simurg_email=email,
    )
    run_main_pipeline(config)


if __name__ == "__main__":
    date = '2026-01-19'
    ionosonde_code = None
    cosmic_stations = None
    email = None

    main(
        date_str=date,
        ionosonde_code=ionosonde_code,
        cosmic_station_codes=cosmic_stations,
        email=email,
    )

