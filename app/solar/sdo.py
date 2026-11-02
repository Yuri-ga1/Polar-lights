"""Explicit per-product SDO acquisition policy and scientific record identity."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC

from astropy.time import Time


def drms_time(value):
    """Parse DRMS TAI without treating its wall clock as UTC."""
    text = str(value)
    scale = "tai" if text.endswith("_TAI") else "utc"
    text = re.sub(r"_(TAI|UTC)$", "", text)
    text = re.sub(r"^(\d{4})\.(\d{2})\.(\d{2})", r"\1-\2-\3", text).replace("_", "T")
    return Time(text, scale=scale)


@dataclass(frozen=True)
class SDOProduct:
    instrument: str = "hmi"
    series: str = "hmi.Ic_720s"
    segment: str = "continuum"
    channel: str = ""
    # Additional prime-key selectors, e.g. '[171]' for aia.lev1_euv_12s.
    selectors: str = ""
    time_key: str = "T_OBS"
    quality_mask: int = 0xFFFFFFFF
    processing_version: str = "1"

    def __post_init__(self):
        for value in (
            self.instrument,
            self.series,
            self.segment,
            self.processing_version,
        ):
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in (".", ".."):
                raise ValueError("Invalid SDO product identifier")
        if self.channel and not re.fullmatch(r"[A-Za-z0-9_-]+", self.channel):
            raise ValueError("Invalid channel")
        if not re.fullmatch(r"(\[[A-Za-z0-9_.+-]+\])*", self.selectors):
            raise ValueError("Use explicit prime-key selectors, not record ranges")
        if not re.fullmatch(r"[A-Za-z0-9_]+", self.time_key):
            raise ValueError("Invalid time keyword")

    @property
    def key(self):
        return hashlib.sha256(
            json.dumps(self.__dict__, sort_keys=True).encode()
        ).hexdigest()

    @property
    def directory(self):
        return f"sdo/{self.instrument}/{self.series}/{self.segment}/{self.channel or 'all'}"


@dataclass(frozen=True)
class JSOCSettings:
    search_window_seconds: float = 1800
    metadata_ttl: float = 3600
    negative_ttl: float = 120
    poll_seconds: float = 60
    wait_timeout: float = 1800
    http_timeout: float = 90
    retries: int = 3
    backoff_seconds: float = 1
    lock_timeout: float = 2100
    quick: bool = True
    keep_fits: bool = False

    def __post_init__(self):
        for name, value in self.__dict__.items():
            if isinstance(value, bool):
                continue
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.poll_seconds < 60:
            raise ValueError("JSOC status polling must be at least 60 seconds apart")
        if not isinstance(self.retries, int):
            raise TypeError("retries must be an integer")


@dataclass(frozen=True)
class SDORecord:
    spec: str
    time_tai: str
    quality: int

    @property
    def utc(self):
        return drms_time(self.time_tai).utc.to_datetime(timezone=UTC)

    def identity(self, product):
        return hashlib.sha256(
            f"{product.key}|{self.spec}|{self.time_tai}".encode()
        ).hexdigest()
