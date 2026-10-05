from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.storage.timeseries import utc


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeriesParameters(StrictModel):
    start: datetime
    end: datetime
    columns: list[str] = Field(min_length=1, max_length=64)

    @field_validator("start", "end")
    @classmethod
    def require_zone(cls, value):
        if value.tzinfo is None or value.microsecond:
            raise ValueError("Use an ISO timestamp with timezone and whole seconds")
        return utc(value).to_pydatetime()

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("columns must be unique")
        return self


class MapParameters(StrictModel):
    timestamp: datetime
    resolution: Literal["full", "medium", "low"] = "full"
    format: Literal["arrow", "json"] = "arrow"

    _zone = field_validator("timestamp")(
        classmethod(SeriesParameters.require_zone.__func__)
    )


class SeriesRequest(StrictModel):
    productId: Literal["omni", "kp", "kyoto-dst", "nmdb", "giro", "timeseries"]
    parameters: SeriesParameters


class MapRequest(StrictModel):
    productId: Literal["roti-map", "tec-adjusted-map", "gim-map"]
    parameters: MapParameters


class AuroraMapParameters(StrictModel):
    timestamp: datetime

    _zone = field_validator("timestamp")(
        classmethod(SeriesParameters.require_zone.__func__)
    )


class AuroraMapRequest(StrictModel):
    productId: Literal["aurora-map"]
    parameters: AuroraMapParameters


class AuroraGeomagneticLinesRequest(StrictModel):
    timestamp: datetime
    latitudes: list[float] = Field(min_length=1)

    _zone = field_validator("timestamp")(
        classmethod(SeriesParameters.require_zone.__func__)
    )

    @field_validator("latitudes")
    @classmethod
    def validate_latitudes(cls, values):
        if any(not -90 <= latitude <= 90 for latitude in values):
            raise ValueError("Geomagnetic latitudes must be between -90 and 90")
        return values


class AuroraGeomagneticLine(BaseModel):
    latitude: float
    paths: list[list[tuple[float, float]]]


class AuroraGeomagneticLinesResponse(BaseModel):
    lines: list[AuroraGeomagneticLine]


class KeogramParameters(StrictModel):
    start: datetime
    end: datetime
    timeStepMinutes: Literal[1, 5, 10, 15, 30, 60] = 5
    latitudeStepDegrees: Literal[1, 2.5, 5, 10] = 2.5
    hemisphere: Literal["west", "east", "all"] = "west"

    _zone = field_validator("start", "end")(
        classmethod(SeriesParameters.require_zone.__func__)
    )

    @model_validator(mode="after")
    def ordered(self):
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        if (self.end.date() - self.start.date()).days > 2:
            raise ValueError("Keogram range cannot exceed three calendar dates")
        return self


class KeogramRequest(StrictModel):
    productId: Literal["roti-keogram", "tec-adjusted-keogram"]
    parameters: KeogramParameters


DataRequest = Annotated[
    SeriesRequest | MapRequest | KeogramRequest | AuroraMapRequest,
    Field(discriminator="productId"),
]


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ParameterSchema(BaseModel):
    name: str
    type: Literal["datetime", "select", "multiselect"]
    required: bool
    default: str | float | list[str] | None = None
    values: list[str | float] | None = None


class CatalogProduct(BaseModel):
    productId: str
    title: str
    category: str
    graphType: Literal["timeseries", "map", "keogram"]
    available: bool
    units: str | dict[str, str]
    parameterSchema: list[ParameterSchema]
    capabilities: dict[str, bool]
    availabilityStrategy: str
    remoteAcquisition: bool
    columnMetadata: dict[str, dict] = Field(default_factory=dict)


class CatalogResponse(BaseModel):
    products: list[CatalogProduct]


class AvailabilityInterval(BaseModel):
    column: str
    start: str
    end: str


class AvailabilityResponse(BaseModel):
    productId: str
    columns: list[str] = Field(default_factory=list)
    intervals: list[AvailabilityInterval] = Field(default_factory=list)
    stations: list[str] = Field(default_factory=list)
    timestamps: list[str] = Field(default_factory=list)
    dates: list[str] = Field(default_factory=list)
    total: int
    nextOffset: int | None
    datasetVersion: str
    generatedAt: str
    source: str | list[str]


class JobStatus(BaseModel):
    jobId: str
    status: Literal[
        "queued", "downloading", "processing", "completed", "failed", "cancelled"
    ]
    createdAt: float
    updatedAt: float
    resultUrl: str
    error: ErrorResponse | None = None
    specHash: str | None = None


class RenderFile(BaseModel):
    name: str
    url: str


class RenderFiles(BaseModel):
    jobId: str
    status: str
    files: list[RenderFile]


class JobAccepted(BaseModel):
    status: Literal["processing"] = "processing"
    jobId: str
    statusUrl: str
    resultUrl: str


class SeriesResponse(BaseModel):
    dataType: Literal["timeseries"] = "timeseries"
    time: list[str]
    columns: dict[str, list[float | None]]
    metadata: dict


class KeogramResponse(BaseModel):
    dataType: Literal["keogram"] = "keogram"
    time: list[str]
    latitude: list[float]
    values: list[list[float | None]]
    metadata: dict


class MapJsonResponse(BaseModel):
    dataType: Literal["map"] = "map"
    lat: list[float]
    lon: list[float]
    value: list[float | None]
    metadata: dict


class AuroraMapResponse(BaseModel):
    dataType: Literal["aurora"] = "aurora"
    observations: list[dict]
    overlays: dict
    metadata: dict


class MapRenderSpec(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    productId: Literal["roti-map", "tec-adjusted-map", "gim-map"]
    timestamps: tuple[datetime, ...] = Field(min_length=1, max_length=48)
    width: int = Field(default=1200, ge=256, le=2400)
    height: int = Field(default=700, ge=256, le=1600)
    center: tuple[float, float] = (0.0, 40.0)
    zoom: float = Field(default=1.0, ge=0, le=10)
    minimum: float = 0
    maximum: float = 1
    resolution: Literal["full", "medium", "low"] = "medium"
    maplibreVersion: Literal["5.6.1"] = "5.6.1"
    playwrightVersion: Literal["1.55.0"] = "1.55.0"
    dpr: Literal[1] = 1
    assetVersion: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("timestamps")
    @classmethod
    def timestamps_utc(cls, values):
        return tuple(SeriesParameters.require_zone(v) for v in values)

    @model_validator(mode="after")
    def validate_bounds(self):
        import math

        if not all(
            math.isfinite(v)
            for v in (*self.center, self.minimum, self.maximum, self.zoom)
        ):
            raise ValueError("Render parameters must be finite")
        if not (-180 <= self.center[0] <= 180 and -85 <= self.center[1] <= 85):
            raise ValueError("Invalid map center")
        if self.maximum <= self.minimum:
            raise ValueError("maximum must exceed minimum")
        dates = [value.date() for value in self.timestamps]
        if (max(dates) - min(dates)).days > 2:
            raise ValueError("Map render range cannot exceed three calendar dates")
        return self
