from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.visualization.plot_settings import DPI


def utc_datetime(value: str | datetime) -> datetime:
    """Interpret ISO dates/naive input as UTC; normalize offsets to UTC."""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class SolarDiskConfig:
    requested_time: str | datetime = "2026-01-20T12:00:00Z"
    source_id: int = 18
    max_time_delta_minutes: float = 30
    annotate_active_regions: bool = True
    force_download: bool = False
    allow_srs_fallback: bool = True
    download_base_dir: str | Path = "files"
    plots_base_dir: str | Path = "results"
    figsize: tuple[float, float] = (9, 9)
    dpi: int = DPI
    filename: str | None = None
    label_offset: tuple[float, float] = (9, 10)
    label_fontsize: float = 11
    colorbar: bool = False
    save: bool = True

    def __post_init__(self):
        object.__setattr__(self, "requested_time", utc_datetime(self.requested_time))
        if self.source_id != 18:
            raise ValueError("SolarDisk supports SDO/HMI Int (source_id=18) only.")
        if self.max_time_delta_minutes < 0:
            raise ValueError("max_time_delta_minutes must be non-negative")
        if self.dpi <= 0 or min(self.figsize) <= 0:
            raise ValueError("dpi and figsize must be positive")
        if self.filename and (
            Path(self.filename).name != self.filename
            or not self.filename.endswith(".png")
        ):
            raise ValueError("filename must be a PNG filename without a directory")

    @property
    def cache_dir(self) -> Path:
        return (
            Path(self.download_base_dir)
            / self.requested_time.strftime("%Y-%m-%d")
            / "solar"
        )

    @property
    def output_path(self) -> Path:
        filename = self.filename or f"Solar_disk_{self.requested_time:%H%M%S}.png"
        return (
            Path(self.plots_base_dir)
            / self.requested_time.strftime("%Y-%m-%d")
            / filename
        )

    @property
    def metadata_path(self) -> Path:
        """Store provenance with downloaded data, separate from rendered plots."""
        return self.cache_dir / Path(self.output_path.name).with_suffix(".json")


@dataclass(frozen=True)
class ActiveRegion:
    number: int
    latitude: float
    longitude: float
    epoch: datetime
    area: int | None
    spot_count: int | None
    magnetic_class: str | None
    mcintosh_class: str | None
    raw_line: str


@dataclass(frozen=True)
class SRSReport:
    issued: datetime
    epoch: datetime
    regions: tuple[ActiveRegion, ...]


@dataclass(frozen=True)
class ProjectedRegion:
    region: ActiveRegion
    x_arcsec: float
    y_arcsec: float
    pixel_x: float
    pixel_y: float


@dataclass
class SolarDiskData:
    solar_map: Any
    regions: list[ProjectedRegion]
    metadata: dict[str, Any]
    config: SolarDiskConfig
