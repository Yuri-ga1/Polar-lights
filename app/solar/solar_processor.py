from __future__ import annotations

import importlib.util
import logging
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import UTC

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from PIL import Image
from sunpy.coordinates import frames
from sunpy.map import Map
from sunpy.physics.differential_rotation import solar_rotate_coordinate

from app.base_classes.base_processor import BaseProcessor
from app.solar.models import ProjectedRegion, SolarDiskData, utc_datetime
from app.solar.solar_downloader import HelioviewerDownloader, SRSDownloader

logger = logging.getLogger(__name__)


def read_jp2_map(path, downloader, image_id):
    """Prefer SunPy's native JP2 reader when its optional backend is available.

    Pillow/OpenJPEG already decodes JP2 in this environment. The fallback mirrors
    SunPy's vertical row flip and uses the API XML WCS, never a pixel-center guess.
    """
    solar_map = None
    if all(importlib.util.find_spec(name) for name in ("glymur", "lxml")):
        try:
            solar_map = Map(path)
        except (OSError, ValueError, ImportError) as exc:
            logger.warning(
                "Native SunPy JP2 reader failed; using Pillow + XML: %s", exc
            )
    if solar_map is None:
        xml_path = downloader.header(image_id)
        root = ET.fromstring(xml_path.read_bytes()).find("fits")
        if root is None:
            raise ValueError("Helioviewer JP2 XML has no WCS header")
        header = {}
        for node in root:
            if not node.text or not node.text.strip():
                continue
            value = node.text.strip()
            try:
                value = float(value)
            except ValueError:
                pass
            header[node.tag.lower()] = value
        with Image.open(path) as image:
            data = np.asarray(image).copy()[::-1]
        solar_map = Map(data, header)
    required = (
        "crpix1",
        "crpix2",
        "crval1",
        "crval2",
        "cdelt1",
        "cdelt2",
        "ctype1",
        "ctype2",
        "cunit1",
        "cunit2",
        "dsun_obs",
        "rsun_obs",
        "rsun_ref",
        "hgln_obs",
    )
    missing = [key for key in required if key not in solar_map.meta]
    if missing or not any(key in solar_map.meta for key in ("hglt_obs", "crlt_obs")):
        raise ValueError(f"Incomplete JP2 WCS/observer metadata: {missing}")
    if not any(key in solar_map.meta for key in ("crota2", "pc1_1", "cd1_1")):
        raise ValueError("JP2 header does not describe image orientation")
    if (
        solar_map.meta.get("ctype1") != "HPLN-TAN"
        or solar_map.meta.get("ctype2") != "HPLT-TAN"
    ):
        raise ValueError("Expected helioprojective HMI WCS")
    return solar_map


class SolarProcessor(BaseProcessor):
    @staticmethod
    def project_regions(report, solar_map):
        """Howard sidereal differential rotation, with changing observer accounted for.

        SRS longitudes are Earth-relative Stonyhurst at the explicit validity
        epoch. Transform to the native HMI WCS reference time (exposure midpoint,
        T_OBS), using its observer. DATE-OBS remains the displayed exposure start.
        """
        projected = []
        for region in report.regions:
            try:
                coordinate = SkyCoord(
                    region.longitude * u.deg,
                    region.latitude * u.deg,
                    solar_map.rsun_meters,
                    frame=frames.HeliographicStonyhurst,
                    obstime=region.epoch,
                    rsun=solar_map.rsun_meters,
                )
                rotated = solar_rotate_coordinate(
                    coordinate, observer=solar_map.observer_coordinate, model="howard"
                )
                hpc = rotated.transform_to(solar_map.coordinate_frame)
                x, y = hpc.Tx.to_value(u.arcsec), hpc.Ty.to_value(u.arcsec)
                if not np.all(np.isfinite([x, y])):
                    raise ValueError("Non-finite helioprojective coordinate")
                # Projected X/Y alone cannot distinguish the back of the Sun.
                if not bool(hpc.is_visible()):
                    continue
                px, py = solar_map.world_to_pixel(hpc)
                if not np.all(np.isfinite([x, y, px.value, py.value])):
                    raise ValueError("Non-finite projected coordinate")
                projected.append(
                    ProjectedRegion(
                        region, float(x), float(y), float(px.value), float(py.value)
                    )
                )
            except (ValueError, TypeError, ArithmeticError) as exc:
                logger.warning(
                    "Skipping NOAA %s (%s): %s", region.number, region.raw_line, exc
                )
        return projected

    def load(self, config):
        with HelioviewerDownloader(config) as downloader:
            closest, path, url = downloader.download()
            solar_map = read_jp2_map(path, downloader, int(closest["id"]))
        observed = solar_map.date.to_datetime(timezone=UTC)
        delta = abs((observed - config.requested_time).total_seconds())
        if delta > config.max_time_delta_minutes * 60:
            raise ValueError(
                f"JP2 observation time {observed.isoformat()} exceeds the requested tolerance"
            )
        if abs((observed - utc_datetime(closest["date"])).total_seconds()) > 2:
            raise ValueError(
                "JP2 observation time does not match the selected Helioviewer frame"
            )
        metadata = {
            "requested_time": config.requested_time.isoformat(),
            "observation_time": observed.isoformat(),
            "coordinate_reference_time": solar_map.reference_date.utc.isot + "Z",
            "time_delta_seconds": delta,
            "helioviewer": {
                "source": "SDO/HMI HMI Int JP2 (Helioviewer)",
                "source_id": config.source_id,
                "image_id": int(closest["id"]),
                "url": url,
                "cache_path": str(path),
                "closest": closest,
            },
            "rotation_model": "SunPy Howard differential rotation (sidereal); native HMI observer and WCS reference epoch",
        }
        regions = []
        if config.annotate_active_regions:
            with SRSDownloader(config) as downloader:
                report, provenance = downloader.download(observed.date())
            regions = self.project_regions(report, solar_map)
            metadata["srs"] = provenance
            metadata["srs"]["region_count"] = len(report.regions)
        metadata["visible_regions"] = [
            {
                **asdict(item),
                "region": {
                    **asdict(item.region),
                    "epoch": item.region.epoch.isoformat(),
                },
            }
            for item in regions
        ]
        return SolarDiskData(solar_map, regions, metadata, config)
