from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from filelock import FileLock

from app.configuration import current
from app.storage.timeseries import iso, utc

from .catalog import KEOGRAMS, MAPS
from .errors import BackendError
from .logging import get_logger
from .models import MapParameters

logger = get_logger(__name__)


class MapService:
    def __init__(self, settings):
        self.settings = settings
        self._indexes = {}
        self._mutex = threading.RLock()

    def directory(self, product):
        path = self.settings.root / "maps" / MAPS[product][0]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def index(self, product):
        """Cache only HDF5 keys, invalidated by file identity/size/mtime."""
        paths = sorted(self.directory(product).glob("*.h5"))
        signature = tuple(
            (str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths
        )
        with self._mutex:
            if product in self._indexes and self._indexes[product][0] == signature:
                return self._indexes[product][1]
            entries = {}
            for path in paths:
                try:
                    with h5py.File(path, "r") as handle:
                        if "data" not in handle:
                            raise ValueError("Missing data group")
                        version = hashlib.sha256(
                            f"{path.name}:{path.stat().st_size}:{path.stat().st_mtime_ns}".encode()
                        ).hexdigest()[:24]
                        for key in handle["data"]:
                            entries[utc(key)] = (path, key, version)
                except (OSError, ValueError) as exc:
                    raise BackendError(
                        "MAP_FILE_CORRUPTED",
                        "Invalid local map file",
                        500,
                        file=path.name,
                    ) from exc
            self._indexes[product] = (signature, entries)
            return entries

    def has(self, product, timestamp):
        return utc(timestamp) in self.index(product)

    def acquire(self, product, timestamp):
        directory = self.directory(product)
        # SIMuRG remote query discovery is account-scoped. Serialize the two
        # SIMuRG products as well as overlapping multi-day requests.
        lock_name = "gim" if product == "gim-map" else "simurg"
        with FileLock(
            str(directory.parent / f".{lock_name}.download.lock"),
            timeout=self.settings.job_timeout,
        ):
            if self.has(product, timestamp):
                return
            start = time.perf_counter()
            try:
                if product == "gim-map":
                    self._acquire_gim(timestamp)
                else:
                    self._acquire_simurg(product, timestamp)
            except BackendError:
                raise
            except Exception as exc:
                raise BackendError(
                    "DOWNLOAD_FAILED", "Map acquisition failed", 502
                ) from exc
            logger.info(
                "productId=%s downloadProcessSeconds=%.3f",
                product,
                time.perf_counter() - start,
            )

    def _acquire_simurg(self, product, timestamp):
        from app.simurg.simurg_client import SimurgClient
        from app.simurg.simurg_downloader import AdjustedTecDownloader, RotiDownloader

        if not self.settings.simurg_email:
            raise BackendError(
                "DATA_NOT_AVAILABLE", "SIMURG_EMAIL is required for remote maps", 503
            )
        raw = self.settings.root / "raw" / "simurg" / MAPS[product][0]
        downloader_type = (
            RotiDownloader if product == "roti-map" else AdjustedTecDownloader
        )
        downloader = downloader_type(
            SimurgClient(self.settings.simurg_email, polling_interval=current()["downloads"]["simurg_map_polling_interval"]), str(raw)
        )
        path = Path(downloader.download(str(utc(timestamp).date())))
        with h5py.File(path, "r") as handle:
            if "data" not in handle:
                raise BackendError(
                    "MAP_FILE_CORRUPTED", "Downloaded map has no data group", 502
                )
        destination = self.directory(product) / path.name
        self._publish_file(path, destination)

    @staticmethod
    def _publish_file(source, destination):
        fd, name = tempfile.mkstemp(dir=destination.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as out, open(source, "rb") as incoming:
                shutil.copyfileobj(incoming, out, 1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)

    def _acquire_gim(self, timestamp):
        from app.simurg.gim_downloader import GimDownloader
        from app.simurg.gim_processor import GimProcessor

        raw = self.settings.root / "raw" / "gim"
        day = str(utc(timestamp).date())
        GimDownloader(str(raw)).download(day)
        slices = GimProcessor(raw).load(day)
        if not slices:
            raise BackendError(
                "PROCESSING_FAILED", "No GIM slices could be parsed", 502
            )
        directory = self.directory("gim-map")
        fd, name = tempfile.mkstemp(dir=directory, suffix=".tmp")
        os.close(fd)
        try:
            with h5py.File(name, "w") as out:
                group = out.create_group("data")
                for slice_time, values in slices.items():
                    group.create_dataset(
                        iso(slice_time), data=values, compression="gzip"
                    )
                out.flush()
            os.replace(name, directory / f"gim_{day}.h5")
        finally:
            Path(name).unlink(missing_ok=True)

    def read(self, product, parameters, *, acquire=True):
        timestamp = utc(parameters.timestamp)
        entries = self.index(product)
        if timestamp not in entries and acquire:
            try:
                self.acquire(product, timestamp)
            except BackendError as exc:
                if not entries or exc.code != "DATA_NOT_AVAILABLE":
                    raise
                nearest = sorted(entries, key=lambda t: abs(t - timestamp))[:4]
                raise BackendError(
                    "TIMESTAMP_NOT_AVAILABLE",
                    "No map at the requested timestamp",
                    404,
                    nearestTimestamps=[iso(t) for t in sorted(nearest)],
                    acquisitionError=exc.body(),
                ) from exc
            entries = self.index(product)
        if timestamp not in entries:
            nearest = sorted(entries, key=lambda t: abs(t - timestamp))[:4]
            raise BackendError(
                "TIMESTAMP_NOT_AVAILABLE",
                "No map at the requested timestamp",
                404,
                nearestTimestamps=[iso(t) for t in sorted(nearest)],
            )
        path, key, version = entries[timestamp]
        stride = {"full": 1, "medium": 4, "low": 16}[parameters.resolution]
        begin = time.perf_counter()
        try:
            with h5py.File(path, "r") as handle:
                dataset = handle["data"][key]
                names = dataset.dtype.names or ()
                value_field = next(
                    (n for n in ("value", "vals", "tec", "roti") if n in names), None
                )
                if (
                    not {"lat", "lon"}.issubset(names)
                    or not value_field
                    or dataset.ndim != 1
                ):
                    raise ValueError("Expected a structured point array")
                count = (len(dataset) + stride - 1) // stride
                if count > self.settings.max_points:
                    raise BackendError(
                        "INVALID_REQUEST",
                        "Map exceeds point limit; request lower resolution",
                        413,
                        pointCount=count,
                        maxPoints=self.settings.max_points,
                    )
                # Only one timestamp, only its three required fields. h5py
                # applies the stride before allocating the result in memory.
                points = dataset.fields(["lat", "lon", value_field])[::stride]
                arrays = {
                    "lat": points["lat"].astype("float32"),
                    "lon": points["lon"].astype("float32"),
                    "value": points[value_field].astype("float32"),
                }
        except BackendError:
            raise
        except (OSError, ValueError, KeyError) as exc:
            raise BackendError(
                "MAP_FILE_CORRUPTED", "Cannot read the map slice", 500
            ) from exc
        valid = np.isfinite(arrays["lat"]) & np.isfinite(arrays["lon"])
        arrays = {k: v[valid] for k, v in arrays.items()}
        metadata = {
            "productId": product,
            "timestamp": iso(timestamp),
            "units": MAPS[product][1],
            "datasetVersion": version,
            "resolution": parameters.resolution,
            "pointCount": len(arrays["lat"]),
            "missingData": int((~np.isfinite(arrays["value"])).sum()),
            "generatedAt": iso(pd.Timestamp.now(tz="UTC")),
            "source": "GIM" if product == "gim-map" else "SIMuRG",
        }
        logger.info(
            "productId=%s readSeconds=%.3f datasetVersion=%s pointCount=%s",
            product,
            time.perf_counter() - begin,
            version,
            metadata["pointCount"],
        )
        return arrays, metadata

    def response(self, product, parameters):
        arrays, metadata = self.read(product, parameters)
        begin = time.perf_counter()
        if parameters.format == "json":
            payload = json.dumps(
                {
                    "dataType": "map",
                    **{
                        k: [float(x) if np.isfinite(x) else None for x in v]
                        for k, v in arrays.items()
                    },
                    "metadata": metadata,
                },
                allow_nan=False,
                separators=(",", ":"),
            ).encode()
            media = "application/json"
        else:
            import pyarrow as pa

            table = pa.table(
                {
                    k: pa.array(v, mask=~np.isfinite(v), type=pa.float32())
                    for k, v in arrays.items()
                }
            )
            table = table.replace_schema_metadata(
                {k: json.dumps(v).encode() for k, v in metadata.items()}
            )
            sink = pa.BufferOutputStream()
            with pa.ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table, max_chunksize=65536)
            payload = sink.getvalue().to_pybytes()
            media = "application/vnd.apache.arrow.stream"
        if len(payload) > self.settings.max_response_bytes:
            raise BackendError("INVALID_REQUEST", "Response exceeds byte limit", 413)
        logger.info(
            "productId=%s serializeSeconds=%.3f responseBytes=%s",
            product,
            time.perf_counter() - begin,
            len(payload),
        )
        return payload, media

    @staticmethod
    def keogram_times(parameters):
        step = f"{parameters.timeStepMinutes}min"
        return pd.date_range(
            utc(parameters.start).ceil(step), utc(parameters.end), freq=step
        )

    def keogram_cached(self, request):
        entries = self.index(KEOGRAMS[request.productId])
        return all(t in entries for t in self.keogram_times(request.parameters))

    def keogram(self, request):
        # Reuse the same scientific reducer as the notebooks. Only one map
        # slice at a time is materialised, never an entire multi-day HDF5 file.
        from app.visualization.keogram_plotter import (
            KeogramConfig,
            build_keogram_matrix_from_slices,
        )

        p = request.parameters
        product = KEOGRAMS[request.productId]
        times = self.keogram_times(p)
        entries = self.index(product)
        missing = [t for t in times if t not in entries]
        errors = []
        for day in sorted({t.normalize() for t in missing}):
            try:
                self.acquire(product, next(t for t in missing if t.normalize() == day))
            except BackendError as exc:
                errors.append(exc.body())
        entries = self.index(product)
        available = [t for t in times if t in entries]
        if not available:
            raise BackendError(
                "DATA_NOT_AVAILABLE",
                "No map slices are available for the keogram",
                404,
                errors=errors,
            )
        cfg = KeogramConfig(
            lat_step_deg=p.latitudeStepDegrees,
            time_step_min=p.timeStepMinutes,
            hemisphere=p.hemisphere,
        )

        def slices():
            for timestamp in available:
                arrays, _ = self.read(
                    product, MapParameters(timestamp=timestamp), acquire=False
                )
                points = np.empty(
                    len(arrays["lat"]),
                    dtype=[("lat", "f4"), ("lon", "f4"), ("vals", "f4")],
                )
                points["lat"], points["lon"], points["vals"] = (
                    arrays["lat"],
                    arrays["lon"],
                    arrays["value"],
                )
                yield timestamp.to_pydatetime(), points

        matrix, sampled, latitudes = build_keogram_matrix_from_slices(
            slices(),
            available,
            p.start,
            p.end,
            cfg,
        )
        # Preserve gaps in the output time axis without interpolation.
        result = pd.DataFrame(matrix, columns=sampled).reindex(columns=times)
        version = hashlib.sha256(
            "|".join(sorted({entries[t][2] for t in available})).encode()
        ).hexdigest()[:24]
        return {
            "dataType": "keogram",
            "time": [iso(t) for t in times],
            "latitude": latitudes.tolist(),
            "values": [
                [None if pd.isna(v) else float(v) for v in row]
                for row in result.to_numpy()
            ],
            "metadata": {
                "datasetVersion": version,
                "source": "SIMuRG",
                "generatedAt": iso(pd.Timestamp.now(tz="UTC")),
                "units": MAPS[product][1],
                "missingTimestamps": [iso(t) for t in times if t not in entries],
                "parameters": p.model_dump(mode="json"),
                "errors": errors,
            },
        }
