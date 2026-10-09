import json
import threading
import time
from collections import OrderedDict, defaultdict

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
from .jobs import report_stage
from .logging import get_logger
from .maps import MapService
from .models import AuroraMapRequest, KeogramRequest, MapRequest

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
        self._geomagnetic_lock = threading.Lock()
        self._geomagnetic_cache = OrderedDict()

    def initialize(self):
        with FileLock(str(self.storage.path) + ".migration.lock", timeout=60):
            if hasattr(self.adapters, "import_legacy"):
                self.adapters.import_legacy(self.storage)

    def catalog(self):
        with self._cache_lock:
            station_path = self.settings.root / "processed" / "nmdb_stations.csv"
            aurora_path = self._aurora_path()
            signature = (
                self.storage.path.stat().st_mtime_ns
                if self.storage.path.exists()
                else None,
                station_path.stat().st_mtime_ns if station_path.exists() else None,
                aurora_path.stat().st_mtime_ns if aurora_path.exists() else None,
            )
            if self._catalog_cache is None or self._catalog_cache[0] != signature:
                aurora_default = None
                if aurora_path.exists():
                    try:
                        dates = pd.to_datetime(
                            pd.read_csv(aurora_path, usecols=["date"])["date"],
                            errors="coerce",
                        ).dropna()
                        if not dates.empty:
                            aurora_default = (
                                dates.max().date().isoformat() + "T00:00:00Z"
                            )
                    except (OSError, ValueError, pd.errors.ParserError):
                        pass
                self._catalog_cache = (
                    signature,
                    catalog(
                        self.storage.read().columns,
                        bool(self.settings.simurg_email),
                        self.adapters.nmdb_station_metadata()
                        if hasattr(self.adapters, "nmdb_station_metadata")
                        else {},
                        aurora_default=aurora_default,
                    ),
                )
            return self._catalog_cache[1]

    def validate(self, request):
        check_product(request.productId)
        if isinstance(request, (MapRequest, AuroraMapRequest)):
            return
        p = request.parameters
        if isinstance(request, KeogramRequest):
            cells = (
                int((p.end - p.start).total_seconds() / (p.timeStepMinutes * 60)) + 1
            ) * int(180 / p.latitudeStepDegrees)
            if (
                p.end.date() - p.start.date()
            ).days > 2 or cells > self.settings.max_cells:
                raise BackendError(
                    "INVALID_REQUEST",
                    "Keogram exceeds three calendar dates or the cell limit",
                    413,
                    maxCalendarDates=3,
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
        if isinstance(request, AuroraMapRequest):
            path = self._aurora_path()
            if not path.exists():
                return False
            try:
                dates = pd.read_csv(path, usecols=["date"])["date"]
                return bool(
                    (
                        pd.to_datetime(dates, errors="coerce").dt.strftime("%Y-%m-%d")
                        == request.parameters.timestamp.date().isoformat()
                    ).any()
                )
            except (OSError, ValueError, pd.errors.ParserError):
                return False
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
                        report_stage("downloading")
                        rows = self.adapters.acquire(source, first, last, needed)
                        if rows is None or rows.empty:
                            raise BackendError(
                                "DATA_NOT_AVAILABLE",
                                "Source returned no samples",
                                404,
                                source=source,
                            )
                        report_stage("processing")
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
        report_stage("processing")
        version = self.storage.version(frame)
        missing = self.storage.missing(
            frame, p.start, p.end, {c: s.policy for c, s in specs.items()}
        )
        column_metadata = {}
        for column, spec in specs.items():
            expected = spec.policy.expected(p.start, p.end)
            station = {}
            if spec.source == "nmdb" and hasattr(
                self.adapters, "nmdb_station_metadata"
            ):
                station = self.adapters.nmdb_station_metadata().get(spec.raw_name, {})
            column_metadata[column] = {
                "source": spec.source,
                "units": spec.units,
                "frequencySeconds": spec.seconds,
                "offsetSeconds": 0,
                **({"station": spec.raw_name, **station} if station else {}),
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
        if isinstance(request, AuroraMapRequest):
            result = self.aurora_map(request)
            payload = json.dumps(
                result, allow_nan=False, separators=(",", ":")
            ).encode()
            if len(payload) > self.settings.max_response_bytes:
                raise BackendError(
                    "INVALID_REQUEST", "Response exceeds byte limit", 413
                )
            return payload, "application/json"
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

    def _aurora_path(self):
        return self.settings.root / "processed" / "aurora_data.csv"

    @staticmethod
    def _normalize_aurora_csv(path):
        columns = ["date", "time", "duration_min", "lat", "lon", "forms", "colors"]
        if not path.exists():
            return pd.DataFrame(columns=columns)
        try:
            combined = pd.read_csv(path)
        except (OSError, pd.errors.ParserError):
            return pd.DataFrame(columns=columns)
        for column in columns:
            if column not in combined:
                combined[column] = (
                    "" if column in {"date", "time", "forms", "colors"} else pd.NA
                )
        combined = combined[columns]
        combined["date"] = pd.to_datetime(
            combined["date"], errors="coerce"
        ).dt.strftime("%Y-%m-%d")
        combined["lat"] = pd.to_numeric(combined["lat"], errors="coerce")
        combined["lon"] = pd.to_numeric(combined["lon"], errors="coerce")
        combined["duration_min"] = pd.to_numeric(
            combined["duration_min"], errors="coerce"
        )
        combined["colors"] = (
            combined["colors"].fillna("").astype(str).str.replace(",", ";", regex=False)
        )
        combined = combined.dropna(subset=["date", "lat", "lon"])
        combined = combined.drop_duplicates(
            subset=["date", "time", "duration_min", "lat", "lon", "forms", "colors"]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_csv(path, index=False)
        return combined

    def _acquire_aurora_sources(self, day, destination):
        """Append observations from both providers into the unified CSV cache."""
        from app.observation.aurorasaurus_loader import fetch_and_process_aurorasaurus
        from app.pipeline.observation_workflow import _fetch_spaceweatherlive

        jobs = (
            lambda: fetch_and_process_aurorasaurus(
                day,
                str(destination),
                download_dir=str(self.settings.root / "raw" / "aurora"),
                auto_download=True,
            ),
            lambda: _fetch_spaceweatherlive(
                day,
                str(destination),
                str(self.settings.root / "raw" / "aurora"),
            ),
        )
        for acquire in jobs:
            try:
                acquire()
            except Exception:
                logger.warning(
                    "Aurora provider acquisition failed date=%s", day, exc_info=True
                )

    def aurora_map(self, request):
        """Read processed Aurora observations for the selected UTC date."""
        timestamp = request.parameters.timestamp
        path = self._aurora_path()
        date_text = timestamp.date().isoformat()
        with FileLock(str(path) + ".acquire.lock", timeout=self.settings.job_timeout):
            has_date = False
            try:
                dates = pd.read_csv(path, usecols=["date"])["date"]
                has_date = bool(
                    (
                        pd.to_datetime(dates, errors="coerce").dt.strftime("%Y-%m-%d")
                        == date_text
                    ).any()
                )
            except (OSError, ValueError, pd.errors.ParserError):
                pass
            # Existing rows in the shared CSV are authoritative;
            # only request provider data when the selected date is absent.
            if not has_date:
                self._acquire_aurora_sources(timestamp.date(), path)
                self._normalize_aurora_csv(path)
        if not path.exists():
            raise BackendError(
                "DATA_NOT_AVAILABLE",
                "No aurora observations are available",
                404,
                date=str(timestamp.date()),
            )
        try:
            frame = pd.read_csv(path)
        except (OSError, pd.errors.ParserError) as exc:
            raise BackendError(
                "STORAGE_ERROR", "Cannot read processed aurora observations", 500
            ) from exc
        required = {"date", "time", "lat", "lon", "colors"}
        if not required.issubset(frame.columns):
            raise BackendError(
                "STORAGE_ERROR", "Aurora observations file has invalid columns", 500
            )
        date_values = pd.to_datetime(frame["date"], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )
        selected = frame.loc[date_values == timestamp.date().isoformat()].copy()
        observations = []
        from matplotlib.colors import to_hex

        from app.visualization.color_utils import get_dominant_color

        for _, row in selected.iterrows():
            lat, lon = (
                pd.to_numeric(row["lat"], errors="coerce"),
                pd.to_numeric(row["lon"], errors="coerce"),
            )
            if (
                pd.isna(lat)
                or pd.isna(lon)
                or not (-90 <= lat <= 90 and -180 <= lon <= 180)
            ):
                continue
            raw_colors = row.get("colors")
            colors = (
                []
                if pd.isna(raw_colors)
                else [
                    v.strip()
                    for v in str(raw_colors).replace(",", ";").split(";")
                    if v.strip()
                ]
            )
            colors = [
                v for v in colors if v.lower() not in {"unknown", "unk", "none", "nan"}
            ]
            sector_colors = []
            for color in colors:
                try:
                    sector_colors.append(to_hex(get_dominant_color(color)))
                except ValueError:
                    continue
            duration = pd.to_numeric(row.get("duration_min", 0), errors="coerce")
            observations.append(
                {
                    "lat": float(lat),
                    "lon": float(lon),
                    "colors": colors,
                    "sectorColors": sector_colors,
                    "time": "" if pd.isna(row.get("time")) else str(row.get("time")),
                    "durationMinutes": float(duration) if pd.notna(duration) else 0.0,
                    "forms": "" if pd.isna(row.get("forms")) else str(row.get("forms")),
                }
            )
        if not observations:
            raise BackendError(
                "DATA_NOT_AVAILABLE",
                "No aurora observations for the selected date",
                404,
                date=str(timestamp.date()),
            )
        overlays = self._aurora_overlays(timestamp.replace(tzinfo=None))
        return {
            "dataType": "aurora",
            "observations": observations,
            "overlays": overlays,
            "metadata": {
                "timestamp": timestamp.isoformat(),
                "source": ["Aurorasaurus", "SpaceWeatherLive"],
                "pointCount": len(observations),
                "datasetVersion": self.storage.version(selected),
                "generatedAt": pd.Timestamp.now(tz="UTC").isoformat(),
            },
        }

    @staticmethod
    def _aurora_overlays(timestamp):
        """Return the terminator and the night-side polygon for the map."""
        import cartopy.crs as ccrs
        import numpy as np

        from app.visualization.geo_utils import get_subsolar_latlon

        subsolar_lat, subsolar_lon = np.deg2rad(get_subsolar_latlon(timestamp))
        shell_angle = np.deg2rad(90 + np.degrees(np.arccos(6371.0 / (6371.0 + 300.0))))
        theta = np.linspace(0, 2 * np.pi, 361)
        center = np.array(
            [
                np.cos(subsolar_lat) * np.cos(subsolar_lon),
                np.cos(subsolar_lat) * np.sin(subsolar_lon),
                np.sin(subsolar_lat),
            ]
        )
        east = np.array([-np.sin(subsolar_lon), np.cos(subsolar_lon), 0.0])
        north = np.array(
            [
                -np.sin(subsolar_lat) * np.cos(subsolar_lon),
                -np.sin(subsolar_lat) * np.sin(subsolar_lon),
                np.cos(subsolar_lat),
            ]
        )
        points = (
            np.cos(shell_angle) * center[:, None]
            + np.sin(shell_angle)
            * (
                east[:, None] * np.cos(theta)[None, :]
                + north[:, None] * np.sin(theta)[None, :]
            )
        ).T
        terminator_points = np.column_stack(
            [
                np.degrees(np.arctan2(points[:, 1], points[:, 0])),
                np.degrees(np.arcsin(np.clip(points[:, 2], -1, 1))),
            ]
        ).tolist()
        terminator = []
        current = []
        for point in terminator_points:
            if current and abs(point[0] - current[-1][0]) > 180:
                if len(current) > 1:
                    terminator.append(current)
                current = []
            current.append(point)
        if len(current) > 1:
            terminator.append(current)

        from shapely.affinity import translate
        from shapely.geometry import Polygon, box

        sun_latitude, sun_longitude = np.degrees([subsolar_lat, subsolar_lon])
        anti_solar_longitude = (sun_longitude + 180 + 180) % 360 - 180
        rotated = ccrs.RotatedPole(
            pole_latitude=-sun_latitude,
            pole_longitude=anti_solar_longitude,
            central_rotated_longitude=0,
        )
        delta = np.degrees(np.arccos(6371.0 / (6371.0 + 300.0)))
        boundary_longitudes = np.linspace(-180, 180, 361)
        x = np.concatenate([boundary_longitudes, [180, -180, -180]])
        y = np.concatenate(
            [
                np.full_like(boundary_longitudes, delta),
                [90, 90, delta],
            ]
        )
        geo_points = ccrs.PlateCarree().transform_points(rotated, x, y)
        longitudes = np.rad2deg(np.unwrap(np.deg2rad(geo_points[:, 0])))
        night_shape = Polygon(np.column_stack([longitudes, geo_points[:, 1]])).buffer(0)
        night_polygons = []
        min_lon, _, max_lon, _ = night_shape.bounds
        for window in range(
            int(np.floor((min_lon + 180) / 360)),
            int(np.floor((max_lon + 180) / 360)) + 1,
        ):
            clipped = night_shape.intersection(
                box(-180 + window * 360, -90, 180 + window * 360, 90)
            )
            if clipped.is_empty:
                continue
            pieces = list(clipped.geoms) if hasattr(clipped, "geoms") else [clipped]
            for piece in pieces:
                if piece.geom_type == "Polygon" and not piece.is_empty:
                    ring = translate(piece, xoff=-360 * window).exterior.coords
                    night_polygons.append(
                        [[float(lon), float(lat)] for lon, lat in ring]
                    )
        return {"terminator": terminator, "nightPolygons": night_polygons}

    @staticmethod
    def _geomagnetic_line_paths(timestamp, latitudes):
        import cartopy.crs as ccrs
        import matplotlib.pyplot as plt
        import numpy as np

        from app.visualization.geo_utils import geomagnetic_lines

        figure = plt.figure()
        try:
            axis = figure.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
            levels = sorted({latitude for latitude in latitudes if latitude != 0})
            equator, contour = geomagnetic_lines(
                axis, date=timestamp, levels=levels or [0], color="orange"
            )
            level_index = {latitude: index for index, latitude in enumerate(levels)}
            lines = []
            for latitude in latitudes:
                segments = (
                    equator.allsegs[0]
                    if latitude == 0
                    else contour.allsegs[level_index[latitude]]
                )
                paths = [
                    segment.astype(float).tolist()
                    for segment in segments
                    if len(segment) > 1 and np.isfinite(segment).all()
                ]
                lines.append({"latitude": float(latitude), "paths": paths})
            return lines
        finally:
            plt.close(figure)

    def aurora_geomagnetic_lines(self, timestamp, latitudes):
        key = (timestamp.replace(tzinfo=None), tuple(float(x) for x in latitudes))
        # Matplotlib and the magnetic-field model share process state. A browser
        # can cancel a request while its server-side calculation is still running.
        with self._geomagnetic_lock:
            lines = self._geomagnetic_cache.get(key)
            if lines is None:
                lines = self._geomagnetic_line_paths(key[0], key[1])
                self._geomagnetic_cache[key] = lines
                if len(self._geomagnetic_cache) > 32:
                    self._geomagnetic_cache.popitem(last=False)
            else:
                self._geomagnetic_cache.move_to_end(key)
        return {"lines": lines}

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
