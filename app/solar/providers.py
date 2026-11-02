"""Provider boundary; visual fallback is explicit in both logs and provenance."""

import logging
from datetime import UTC
from urllib.error import URLError

import requests
from filelock import Timeout

from app.solar.jsoc_provider import JSOCError, JSOCProvider
from app.solar.jsoc_transport import JSOCTransportError
from app.solar.models import utc_datetime
from app.solar.solar_downloader import HelioviewerDownloader

logger = logging.getLogger(__name__)


class HelioviewerProvider:
    def get(self, config):
        from app.solar.solar_processor import read_jp2_map

        with HelioviewerDownloader(config) as downloader:
            closest, path, url = downloader.download()
            solar_map = read_jp2_map(path, downloader, int(closest["id"]))
        observed = solar_map.date.utc.to_datetime(timezone=UTC)
        if (
            abs((observed - config.requested_time).total_seconds())
            > config.max_time_delta_minutes * 60
        ):
            raise ValueError("JP2 observation time exceeds the requested tolerance")
        if abs((observed - utc_datetime(closest["date"])).total_seconds()) > 2:
            raise ValueError("JP2 time does not match selected Helioviewer frame")
        return solar_map, {
            "provider": "helioviewer",
            "scientific": False,
            "helioviewer": {
                "source": "SDO/HMI HMI Int JP2 (Helioviewer)",
                "source_id": config.source_id,
                "image_id": int(closest["id"]),
                "url": url,
                "cache_path": str(path),
                "closest": closest,
            },
        }


def load_disk(config):
    if config.provider == "helioviewer":
        return HelioviewerProvider().get(config)
    provider = JSOCProvider(config.download_base_dir, config.sdo_product, config.jsoc)
    try:
        solar_map, provenance = provider.get(
            config.requested_time,
            email=config.jsoc_email,
            tolerance_seconds=config.max_time_delta_minutes * 60,
        )
        return solar_map, {**provenance, "jsoc": provenance}
    except (
        JSOCError,
        JSOCTransportError,
        OSError,
        URLError,
        requests.RequestException,
        Timeout,
    ) as exc:
        if config.provider == "jsoc":
            raise
        # An AIA request must never silently turn into an HMI continuum.
        if (
            config.sdo_product.instrument.lower() != "hmi"
            or config.sdo_product.segment != "continuum"
        ):
            raise
        logger.warning(
            "JSOC unavailable; using visual Helioviewer JP2 fallback",
            extra={"event": "sdo_visual_fallback"},
        )
        solar_map, metadata = HelioviewerProvider().get(config)
        return solar_map, {
            **metadata,
            "fallback": True,
            "fallback_reason": type(exc).__name__,
        }
    finally:
        provider.close()
