from __future__ import annotations

from datetime import date, datetime, timedelta

from app.pipeline.observation_workflow import run_observation_workflow


def run_aurora_pipeline(target_date: date, download_dir: str, plots_dir: str) -> None:
    run_observation_workflow(
        date=target_date,
        download_dir=download_dir,
        plots_dir=plots_dir,
        plot_time=datetime.combine(target_date, datetime.min.time()) + timedelta(hours=2),
    )
