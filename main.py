import os
os.environ["MPLBACKEND"] = "Agg"

import argparse
import logging

from app.pipeline.main_pipeline import MainPipelineConfig, run_main_pipeline
from app.visualization.plot_settings import set_plt_def_params


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Единая точка входа для скачивания данных и построения графиков.",
    )
    parser.add_argument("--date", required=True, help="Дата в формате YYYY-MM-DD")
    parser.add_argument(
        "--ionosonde-code",
        default=None,
        help="Код ионозонда (например, MOHE)",
    )
    parser.add_argument(
        "--cosmic-stations",
        nargs="*",
        default=None,
        help="Список кодов станций NMDB для построения вариаций космических лучей",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Email для SimurgClient (опционально; если не задан, используется SIMURG_EMAIL)",
    )
    return parser.parse_args()


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
    args = parse_args()
    main(
        date_str=args.date,
        ionosonde_code=args.ionosonde_code,
        cosmic_station_codes=args.cosmic_stations,
        email=args.email,
    )
