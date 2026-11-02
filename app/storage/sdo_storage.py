"""Immutable one-observation HDF5 files: no full-month copy on append."""

import hashlib
import json
import uuid

import h5py
import numpy as np
from astropy.io import fits
from filelock import FileLock
from sunpy.map import Map
from sunpy.time import parse_time

from app.storage.atomic import publish
from app.storage.data_paths import DataPaths


class SDOValidationError(ValueError):
    pass


def validate_sdo_map(solar_map):
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
        "t_obs",
        "date-obs",
        "bunit",
    )
    meta = solar_map.meta
    if any(key not in meta for key in required):
        raise SDOValidationError(
            "Incomplete scientific WCS/observer/time/unit metadata"
        )
    if not any(key in meta for key in ("hglt_obs", "crlt_obs")) or not any(
        key in meta for key in ("crota2", "pc1_1", "cd1_1")
    ):
        raise SDOValidationError("Missing observer latitude or image orientation")
    data = solar_map.data
    if data.ndim != 2 or data.dtype.kind not in "iuf" or not np.isfinite(data).any():
        raise SDOValidationError("Expected finite two-dimensional scientific pixels")
    if meta["ctype1"] != "HPLN-TAN" or meta["ctype2"] != "HPLT-TAN":
        raise SDOValidationError("Expected helioprojective WCS")
    parse_time(meta["date-obs"])
    parse_time(meta["t_obs"])
    solar_map.wcs.to_header()
    _ = solar_map.observer_coordinate, solar_map.reference_date


def read_scientific_fits(path):
    try:
        with fits.open(path, memmap=False, checksum=True) as hdus:
            for hdu in hdus:
                if hdu.data is None or hdu.data.ndim != 2:
                    continue
                if "CHECKSUM" in hdu.header and hdu.verify_checksum() != 1:
                    raise SDOValidationError("Invalid FITS checksum")
                header = hdus[0].header.copy()
                header.update(hdu.header)
                data = hdu.data.copy()
                solar_map = Map(data, header)
                validate_sdo_map(solar_map)
                return solar_map, header
    except (OSError, ValueError, TypeError) as exc:
        raise SDOValidationError("Invalid scientific FITS") from exc
    raise SDOValidationError("No two-dimensional FITS image")


def sha256(path):
    result = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class SDOImageStorage:
    def __init__(self, paths: DataPaths):
        self.paths = paths

    def path(self, product, record):
        return self.paths.map_dir(product.directory) / f"{record.identity(product)}.h5"

    @staticmethod
    def read(path):
        with h5py.File(path, "r") as handle:
            data = handle["image"][:]
            header = fits.Header.fromstring(handle.attrs["fits_header"], sep="\n")
            result = Map(data, header)
            validate_sdo_map(result)
            return result

    def write(self, product, record, solar_map, header):
        destination = self.path(product, record)
        with FileLock(str(destination) + ".lock"):
            if destination.exists():
                existing = self.read(destination)
                np.testing.assert_array_equal(existing.data, solar_map.data)
                if existing.data.dtype != solar_map.data.dtype:
                    raise SDOValidationError("Existing image has a different dtype")
                return destination
            temporary = destination.with_suffix(f".{uuid.uuid4().hex}.tmp")
            try:
                with h5py.File(temporary, "w") as handle:
                    handle.create_dataset(
                        "image", data=solar_map.data, compression="lzf", shuffle=True
                    )
                    handle.attrs["fits_header"] = header.tostring(sep="\n")
                    handle.attrs["provenance"] = json.dumps(
                        {
                            "product": product.__dict__,
                            "record": record.__dict__,
                            "observation_utc": record.utc.isoformat(),
                        }
                    )
                restored = self.read(temporary)
                np.testing.assert_array_equal(restored.data, solar_map.data)
                if restored.data.dtype != solar_map.data.dtype:
                    raise SDOValidationError("Scientific dtype changed")
                if restored.wcs.to_header() != solar_map.wcs.to_header():
                    raise SDOValidationError("WCS changed during storage")
                publish(temporary, destination)
                # Confirm final pathname is readable before permitting raw cleanup.
                self.read(destination)
                return destination
            finally:
                temporary.unlink(missing_ok=True)
