from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


MAP_PLOT_NAMES = {
    "roti",
    "gim",
    "adjusted tec",
    "tec adjusted",
    "keogram",
    "aurora observation",
    "aurora",
}
HIST_PLOT_NAMES = {"kp"}
SOURCE_PLOT_NAMES = {
    "ionosonde",
    "cosmic ray",
    "cosmic rays",
    "omni",
}

TIME_COLUMN_CANDIDATES = ("datetime", "DateTime", "time", "timestamp")
IONOSONDE_COLUMNS = ("dfoF2", "dhmF2")

SERVICE_COLUMNS = {
    "datetime",
    "time",
    "timestamp",
    "date",
    "hour",
    "year",
    "doy",
    "hr",
    "mn",
}

@dataclass(frozen=True)
class PlotDescriptor:
    name: str
    plot_type: str
    source_key: str
    column: str | None = None


@dataclass(frozen=True)
class ParsedPlot:
    descriptor: PlotDescriptor
    params: dict[str, Any]
    data: Any
    column: str | None = None


@dataclass(frozen=True)
class PlotPanel:
    descriptor: PlotDescriptor
    params: dict[str, Any]
    data: Any
    column: str | None = None
    panel_name: str | None = None
    map_times: tuple[datetime, ...] = ()
