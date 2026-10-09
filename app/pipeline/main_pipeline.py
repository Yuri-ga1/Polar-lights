from __future__ import annotations

import logging
import json
import os
import threading
from contextvars import copy_context
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

from app.pipeline.adjusted_tec_pipeline import run_adjusted_tec_pipeline
from app.pipeline.aurora_pipeline import run_aurora_pipeline
from app.pipeline.observation_workflow import ObservationSource
from app.pipeline.misc_pipeline import run_misc_pipeline
from app.pipeline.roti_pipeline import run_roti_pipeline
from app.simurg.simurg_client import SimurgClient

from app.logging_config import logged_stage
from app.configuration import current, manager, pin

logger = logging.getLogger(__name__)


@dataclass(frozen=True, init=False)
class MainPipelineConfig:
    date_str: str
    download_base_dir: str = "files"
    plots_base_dir: str = "results"
    ionosonde_code: str | None = None
    cosmic_station_codes: list[str] | None = None
    simurg_email: str | None = None
    map_projection: str | None = None
    observation_source: ObservationSource = "aurorasaurus"
    _snapshot: dict = field(default_factory=dict, repr=False, compare=False)

    def __init__(self, date_str: str, download_base_dir: str | None = None,
                 plots_base_dir: str | None = None, ionosonde_code: str | None = None,
                 cosmic_station_codes: list[str] | None = None,
                 simurg_email: str | None = None, map_projection: str | None = None,
                 observation_source: ObservationSource | None = None):
        snapshot = current()
        values = {
            "date_str": date_str,
            "download_base_dir": download_base_dir if download_base_dir is not None else snapshot["backend"]["root"],
            "plots_base_dir": plots_base_dir if plots_base_dir is not None else snapshot["pipeline"]["plots_base_dir"],
            "ionosonde_code": ionosonde_code,
            "cosmic_station_codes": cosmic_station_codes,
            "simurg_email": simurg_email,
            "map_projection": map_projection,
            "observation_source": observation_source if observation_source is not None else snapshot["pipeline"]["observation_source"],
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_snapshot", snapshot)


@dataclass(frozen=True)
class ThreadSpec:
    name: str
    target: Callable[..., None]
    kwargs: dict


def _build_simurg_client(config: MainPipelineConfig) -> SimurgClient | None:
    email = config.simurg_email or os.getenv("SIMURG_EMAIL") or 'Storm_Plotter_Jupyter_Notebook@gmail.com'
    if not email:
        logger.warning("SIMuRG email is missing; adjusted TEC and ROTI pipelines skipped.")
        return None
    return SimurgClient(email=email)


def _build_thread_specs(config: MainPipelineConfig, simurg_client: SimurgClient | None) -> list[ThreadSpec]:
    target_date = date.fromisoformat(config.date_str)
    # Raw/processed/maps are shared stores, never date-nested directories.
    date_download_dir = config.download_base_dir
    date_plots_dir = f"{config.plots_base_dir}/{config.date_str}"
    return [
        ThreadSpec(
            name="adjusted-tec-pipeline",
            target=run_adjusted_tec_pipeline,
            kwargs={
                "date_str": config.date_str,
                "download_dir": date_download_dir,
                "plots_dir": date_plots_dir,
                "simurg_client": simurg_client,
                "map_projection": config.map_projection,
            },
        ),
        ThreadSpec(
            name="roti-pipeline",
            target=run_roti_pipeline,
            kwargs={
                "date_str": config.date_str,
                "download_dir": date_download_dir,
                "plots_dir": date_plots_dir,
                "simurg_client": simurg_client,
                "map_projection": config.map_projection,
            },
        ),
        ThreadSpec(
            name="aurora-map-pipeline",
            target=run_aurora_pipeline,
            kwargs={
                "target_date": target_date,
                "download_dir": date_download_dir,
                "plots_dir": date_plots_dir,
                "map_projection": config.map_projection,
                "source": config.observation_source,
            },
        ),
        ThreadSpec(
            name="misc-pipeline",
            target=run_misc_pipeline,
            kwargs={
                "date_str": config.date_str,
                "download_dir": date_download_dir,
                "plots_dir": date_plots_dir,
                "ionosonde_code": config.ionosonde_code,
                "cosmic_stations": config.cosmic_station_codes,
                "map_projection": config.map_projection,
            },
        ),
    ]


@logged_stage("pipeline", entry=True)
def run_main_pipeline(config: MainPipelineConfig) -> None:
    manager().start()
    with pin(config._snapshot or current()) as snapshot:
        _run_main_pipeline(config, snapshot)


def _run_main_pipeline(config: MainPipelineConfig, snapshot) -> None:
    output = Path(config.plots_base_dir) / config.date_str
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / "effective-config.tmp"
    temporary.write_text(json.dumps({"settings": snapshot, "job": {
        "date_str": config.date_str,
        "download_base_dir": config.download_base_dir,
        "plots_base_dir": config.plots_base_dir,
        "ionosonde_code": config.ionosonde_code,
        "cosmic_station_codes": config.cosmic_station_codes,
        "map_projection": config.map_projection,
        "observation_source": config.observation_source,
    }}, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(output / "effective-config.json")
    simurg_client = _build_simurg_client(config)
    specs = _build_thread_specs(config, simurg_client)
    exceptions: list[tuple[str, BaseException]] = []
    lock = threading.Lock()

    def run_with_capture(spec: ThreadSpec) -> None:
        try:
            spec.target(**spec.kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Pipeline thread failed: %s", spec.name, extra={"event": "pipeline_thread_failed"})
            with lock:
                exceptions.append((spec.name, exc))

    threads = [
        threading.Thread(
            target=copy_context().run,
            args=(run_with_capture,),
            name=spec.name,
            kwargs={"spec": spec},
        )
        for spec in specs
    ]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    if exceptions:
        details = ";\n\t".join(f"{name}: {exc}" for name, exc in exceptions)
        raise RuntimeError(f"Часть потоков завершилась с ошибками:\n\t{details}")
