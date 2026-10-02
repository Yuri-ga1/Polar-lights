import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path = field(
        default_factory=lambda: Path(os.getenv("POLAR_DATA_ROOT", "files"))
    )
    max_samples: int = 200_000
    max_cells: int = 1_000_000
    max_points: int = 2_000_000
    max_response_bytes: int = 64 * 1024 * 1024
    max_days: int = 31
    job_timeout: int = 1800
    job_workers: int = 2
    max_jobs: int = 32
    simurg_email: str = field(default_factory=lambda: os.getenv("SIMURG_EMAIL", ""))
    api_key: str = field(default_factory=lambda: os.getenv("POLAR_API_KEY", ""))
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            filter(None, os.getenv("POLAR_CORS_ORIGINS", "").split(","))
        )
    )
    render_assets: Path = field(
        default_factory=lambda: Path(
            os.getenv("POLAR_RENDER_ASSETS", "files/render-assets")
        )
    )
