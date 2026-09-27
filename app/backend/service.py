import json
import threading
import time
from collections import defaultdict

import pandas as pd
from filelock import FileLock

from app.base_classes.base_processor import BaseProcessor
from app.storage.timeseries import TimeSeriesStorage, iso, utc

from .adapters import SourceAdapters
from .catalog import (
    KEOGRAMS,
    MAPS,
    catalog,
    check_product,
    column_spec,
    product_columns,
    validate_columns,
)
from .errors import BackendError
from .logging import get_logger
from .maps import MapService
from .models import KeogramRequest, MapRequest

logger = get_logger(__name__)


class DataService:
    def __init__(self, settings, adapters=None):
        self.settings = settings
        self.storage = TimeSeriesStorage(settings.root / "processed" / "data.csv")
        self.adapters = adapters or SourceAdapters(settings.root)
        self.maps = MapService(settings)
        self._availability = {}
        self._cache_lock = threading.RLock()
        self._catalog_cache = None

    def initialize(self):
        with FileLock(str(self.storage.path) + ".migration.lock", timeout=60):
            if hasattr(self.adapters, "import_legacy"):
                self.adapters.import_legacy(self.storage)

    def catalog(self):
        with self._cache_lock:
            signature = (
                self.storage.path.stat().st_mtime_ns
                if self.storage.path.exists()
                else None
            )
            if self._catalog_cache is None or self._catalog_cache[0] != signature:
                self._catalog_cache = (
                    signature,
                    catalog(
                        self.storage.read().columns, bool(self.settings.simurg_email)
                    ),
                )
            return self._catalog_cache[1]

    def validate(self, request):
        check_product(request.productId)
        if isinstance(request, MapRequest):
            return
        p = request.parameters
        if isinstance(request, KeogramRequest):
            cells = (
                int((p.end - p.start).total_seconds() / (p.timeStepMinutes * 60)) + 1
            ) * int(180 / p.latitudeStepDegrees)
            if (
                p.end - p.start
            ).total_seconds() > 31 * 86400 or cells > self.settings.max_cells:
                raise BackendError(
                    "INVALID_REQUEST", "Keogram exceeds range or cell limit", 413
                )
            return
        validate_columns(request.productId, p.columns)
        if (p.end - p.start).total_seconds() > self.settings.max_days * 86400:
            raise BackendError(
                "INVALID_REQUEST",
                "Requested range exceeds limit",
                413,
                maxDays=self.settings.max_days,
            )
        samples = sum(
            int((p.end - p.start).total_seconds() / column_spec(c).seconds) + 1
            for c in p.columns
        )
        if samples > self.settings.max_cells:
            raise BackendError(
                "INVALID_REQUEST",
                "Requested data exceeds sample limit",
                413,
                maxCells=self.settings.max_cells,
            )

    def cached(self, request):
        self.validate(request)
        if isinstance(request, MapRequest):
            return self.maps.has(request.productId, request.parameters.timestamp)
        if isinstance(request, KeogramRequest):
            return self.maps.keogram_cached(request)
        p = request.parameters
        policies = {c: column_spec(c).policy for c in p.columns}
        return not any(
            self.storage.missing(self.storage.read(), p.start, p.end, policies).values()
        )

    def _acquire(self, start, end, specs, errors):
        by_source = defaultdict(list)
        for column, spec in specs.items():
            by_source[spec.source].append(column)
        for source, columns in by_source.items():
            # Separate from the CSV lock: downloads for different sources can
            # run concurrently. Recheck after waiting, including overlapping gaps.
            lock_path = self.storage.path.parent / f".{source}.acquire.lock"
            with FileLock(str(lock_path), timeout=self.settings.job_timeout):
                current = self.storage.read()
                missing = self.storage.missing(
                    current, start, end, {c: specs[c].policy for c in columns}
                )
                grouped = defaultdict(list)
                for column, intervals in missing.items():
                    for interval in intervals:
                        grouped[interval].append(column)
                for (first, last), needed in sorted(grouped.items()):
                    logger.info(
                        "source=%s missingInterval=%s/%s columns=%s",
                        source,
                        iso(first),
                        iso(last),
                        needed,
                    )
                    try:
                        rows = self.adapters.acquire(source, first, last, needed)
                        if rows is None or rows.empty:
                            raise BackendError(
                                "DATA_NOT_AVAILABLE",
                                "Source returned no samples",
                                404,
                                source=source,
                            )
                        normalized = (
                            TimeSeriesStorage.normalize(rows)
                            .reindex(columns=needed)
                            .loc[first:last]
                        )
                        begin = time.perf_counter()
                        self.storage.merge(normalized)
                        logger.info(
                            "source=%s storageUpdateSeconds=%.3f",
                            source,
                            time.perf_counter() - begin,
                        )
                    except BackendError as exc:
                        errors.append(exc.body())

    def series(self, request):
        self.validate(request)
        p = request.parameters
        specs = validate_columns(request.productId, p.columns)
        errors = []
        begin = time.perf_counter()
        frame = BaseProcessor().get_data(
            self.storage.path,
            p.start,
            p.end,
            lambda missing: self._acquire(p.start, p.end, specs, errors),
            columns=p.columns,
            frequency_policies={c: s.policy for c, s in specs.items()},
        )
        # Include absent expected samples, but do not invent values or repeat
        # sparse samples at the cadence of the densest source.
        index = pd.DatetimeIndex([], tz="UTC")
        for spec in specs.values():
            index = index.union(spec.policy.expected(p.start, p.end))
        index = index.union(frame.dropna(how="all").index).sort_values()
        if (
            len(index) > self.settings.max_samples
            or len(index) * len(specs) > self.settings.max_cells
        ):
            raise BackendError("INVALID_REQUEST", "Response exceeds cell limit", 413)
        frame = frame.reindex(index)
        if frame.notna().sum().sum() == 0 and len(index):
            if errors:
                error = errors[0]
                raise BackendError(
                    error["code"],
                    error["message"],
                    502 if error["code"] != "DATA_NOT_AVAILABLE" else 404,
                    **error["details"],
                )
            raise BackendError(
                "DATA_NOT_AVAILABLE",
                "No samples available for the requested columns",
                404,
            )
        version = self.storage.version(frame)
        missing = self.storage.missing(
            frame, p.start, p.end, {c: s.policy for c, s in specs.items()}
        )
        column_metadata = {}
        for column, spec in specs.items():
            expected = spec.policy.expected(p.start, p.end)
            column_metadata[column] = {
                "source": spec.source,
                "units": spec.units,
                "frequencySeconds": spec.seconds,
                "offsetSeconds": 0,
                "datasetVersion": self.storage.version(frame[[column]].dropna()),
                "missingIntervals": [[iso(a), iso(b)] for a, b in missing[column]],
                "missingCount": int(frame.reindex(expected)[column].isna().sum()),
            }
        result = {
            "dataType": "timeseries",
            "time": [iso(t) for t in index],
            "columns": {
                c: [None if pd.isna(v) else float(v) for v in frame[c]] for c in specs
            },
            "metadata": {
                "datasetVersion": version,
                "generatedAt": iso(pd.Timestamp.now(tz="UTC")),
                "source": sorted({s.source for s in specs.values()}),
                "columnMetadata": column_metadata,
                "units": {c: s.units for c, s in specs.items()},
                "frequency": {c: f"{s.seconds}s" for c, s in specs.items()},
                "nullPolicy": {
                    "missing_data": "null at an expected sample",
                    "no_sample_expected": "null outside the column UTC sampling grid",
                },
                "partial": bool(errors) or any(missing.values()),
                "errors": errors,
            },
        }
        logger.info(
            "productId=%s readProcessSeconds=%.3f datasetVersion=%s",
            request.productId,
            time.perf_counter() - begin,
            version,
        )
        return result

    def response(self, request):
        if isinstance(request, MapRequest):
            return self.maps.response(request.productId, request.parameters)
        result = (
            self.maps.keogram(request)
            if isinstance(request, KeogramRequest)
            else self.series(request)
        )
        begin = time.perf_counter()
        payload = json.dumps(result, allow_nan=False, separators=(",", ":")).encode()
        if len(payload) > self.settings.max_response_bytes:
            raise BackendError("INVALID_REQUEST", "Response exceeds byte limit", 413)
        logger.info(
            "productId=%s serializeSeconds=%.3f responseBytes=%d",
            request.productId,
            time.perf_counter() - begin,
            len(payload),
        )
        return payload, "application/json"

    def availability(self, product, start=None, end=None, offset=0, limit=1000):
        check_product(product)
        if product in KEOGRAMS:
            result = self.availability(KEOGRAMS[product], start, end, offset, limit)
            return {**result, "productId": product}
        if start and end and utc(end) < utc(start):
            raise BackendError("INVALID_REQUEST", "end precedes start", 422)
        if product in MAPS:
            entries = self.maps.index(product)
            selected = sorted(
                t
                for t in entries
                if (not start or t >= utc(start)) and (not end or t <= utc(end))
            )
            page = selected[offset : offset + limit]
            return {
                "productId": product,
                "timestamps": [iso(t) for t in page],
                "dates": sorted({str(t.date()) for t in page}),
                "total": len(selected),
                "nextOffset": offset + limit
                if offset + limit < len(selected)
                else None,
                "datasetVersion": self._map_version(entries),
                "generatedAt": iso(pd.Timestamp.now(tz="UTC")),
                "source": "GIM" if product == "gim-map" else "SIMuRG",
            }
        signature = (
            (self.storage.path.stat().st_mtime_ns, self.storage.path.stat().st_size)
            if self.storage.path.exists()
            else None
        )
        key = (product, str(start), str(end), offset, limit, signature)
        with self._cache_lock:
            if key in self._availability:
                return self._availability[key]
        frame = self.storage.read()
        columns = (
            list(frame.columns)
            if product == "timeseries"
            else product_columns(product, frame.columns)
        )
        columns = [c for c in columns if c in frame and self._supported_column(c)]
        if start:
            frame = frame.loc[utc(start) :]
        if end:
            frame = frame.loc[: utc(end)]
        intervals = []
        for c in columns:
            for a, b in column_spec(c).policy.intervals(frame.index[frame[c].notna()]):
                intervals.append({"column": c, "start": iso(a), "end": iso(b)})
        result = {
            "productId": product,
            "columns": columns,
            "intervals": intervals[offset : offset + limit],
            "total": len(intervals),
            "nextOffset": offset + limit if offset + limit < len(intervals) else None,
            "stations": sorted(
                {
                    c.split("_")[1].upper()
                    for c in columns
                    if c.startswith(("nmdb_", "giro_"))
                }
            ),
            "datasetVersion": self.storage.version(frame.reindex(columns=columns)),
            "generatedAt": iso(pd.Timestamp.now(tz="UTC")),
            "source": sorted({column_spec(c).source for c in columns}),
        }
        with self._cache_lock:
            if len(self._availability) >= 64:
                self._availability.clear()
            self._availability[key] = result
        return result

    @staticmethod
    def _supported_column(column):
        try:
            column_spec(column)
            return True
        except BackendError:
            return False

    @staticmethod
    def _map_version(entries):
        import hashlib

        return hashlib.sha256(
            "|".join(sorted({v[2] for v in entries.values()})).encode()
        ).hexdigest()[:24]
