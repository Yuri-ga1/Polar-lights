from __future__ import annotations

from datetime import date, datetime, timedelta

from app.pipeline.observation_workflow import run_observation_workflow


def run_aurora_pipeline(target_date: date, base_out_dir: str) -> None:
    run_observation_workflow(
        dates=[target_date],
        base_out_dir=base_out_dir,
        plot_time=datetime.combine(target_date, datetime.min.time()) + timedelta(hours=2),
    )
