"""Local-first acquisition of one nearest scientific observation."""

import json
import logging
import time
from datetime import timedelta

from filelock import FileLock

from app.solar.jsoc_index import JSOCIndex
from app.solar.jsoc_transport import DRMSClient, ExportUnavailable, JSOCTransportError
from app.solar.sdo import JSOCSettings, SDOProduct
from app.storage.data_paths import DataPaths
from app.storage.raw_retention import raw_operation
from app.storage.sdo_storage import (
    SDOImageStorage,
    SDOValidationError,
    read_scientific_fits,
    sha256,
)

logger = logging.getLogger(__name__)


class JSOCError(RuntimeError):
    pass


class JSOCProvider:
    def __init__(self, root="files", product=None, settings=None, client=None):
        self.paths = DataPaths.from_root(root)
        self.product = product or SDOProduct()
        self.settings = settings or JSOCSettings()
        self.index = JSOCIndex(self.paths)
        self.storage = SDOImageStorage(self.paths)
        self._client = client
        self._owned_client = client is None

    @property
    def client(self):
        if self._client is None:
            self._client = DRMSClient(self.settings)
        return self._client

    def close(self):
        if self._owned_client and self._client is not None:
            self._client.close()

    def _event(self, event):
        logger.info(
            event, extra={"event": event, "context": {"series": self.product.series}}
        )

    def _local(self, records):
        corrupt = False
        for record in records:
            artifact = self.index.artifact(record.identity(self.product))
            # Deterministic path also recovers a crash after rename before SQLite commit.
            path = self.storage.path(self.product, record)
            if not path.is_file():
                continue
            try:
                if artifact.get("checksum") and sha256(path) != artifact["checksum"]:
                    raise SDOValidationError("Stored image checksum mismatch")
                solar_map = self.storage.read(path)
                self._validate_record(solar_map, record)
                self._event("sdo_local_hit")
                return solar_map, self._provenance(record, path)
            except (OSError, ValueError, KeyError):
                # Keep a damaged permanent file for inspection; do not overwrite it.
                logger.warning("Invalid permanent SDO artifact; recovery required")
                corrupt = True
        if corrupt:
            raise JSOCError(
                "Corrupt permanent SDO artifact; restore from backup before acquisition"
            )
        return None

    def _raw(self, records):
        folder = self.paths.raw_source(self.product.directory)
        for record in records:
            raw = folder / f"{record.identity(self.product)}.fits"
            if not raw.is_file():
                continue
            with raw_operation(folder, timeout=self.settings.lock_timeout) as operation:
                try:
                    return self._publish(record, raw, operation)
                except SDOValidationError:
                    self._event("sdo_raw_invalid")
        return None

    def _provenance(self, record, path):
        return {
            "provider": "jsoc",
            "scientific": True,
            "series": self.product.series,
            "segment": self.product.segment,
            "record": record.spec,
            "record_time_tai": record.time_tai,
            "record_time_utc": record.utc.isoformat(),
            "quality": record.quality,
            "map_path": str(path),
        }

    def _validate_record(self, solar_map, record):
        instrument = str(solar_map.meta.get("instrume", "")).lower()
        if not instrument.startswith(self.product.instrument.lower()):
            raise SDOValidationError("FITS instrument differs from requested product")
        if self.product.channel.isdigit() and float(
            solar_map.meta.get("wavelnth", -1)
        ) != float(self.product.channel):
            raise SDOValidationError("FITS wavelength differs from requested channel")
        if (
            abs(
                (
                    solar_map.reference_date.utc.to_datetime(timezone=record.utc.tzinfo)
                    - record.utc
                ).total_seconds()
            )
            > 2
        ):
            raise SDOValidationError(
                "FITS reference time differs from selected observation"
            )
        quality = solar_map.meta.get("quality")
        if quality is not None and int(quality) & self.product.quality_mask:
            raise SDOValidationError("FITS QUALITY is unsuitable")

    def get(self, target, *, email, tolerance_seconds=1800):
        from app.solar.models import utc_datetime

        target = utc_datetime(target)
        if not email or "@" not in email:
            raise ValueError("A registered JSOC email is required")
        if (
            tolerance_seconds < 0
            or tolerance_seconds > self.settings.search_window_seconds
        ):
            raise ValueError(
                "Tolerance must be nonnegative and within the metadata search window"
            )
        start, end = (
            (target - timedelta(seconds=tolerance_seconds)).timestamp(),
            (target + timedelta(seconds=tolerance_seconds)).timestamp(),
        )

        def candidates():
            return sorted(
                self.index.candidates(self.product, start, end),
                key=lambda record: (
                    abs((record.utc - target).total_seconds()),
                    record.utc,
                ),
            )

        # Lock covers all overlapping queries for a product, across processes.
        # Kernel file locks are released on death; there are no stale TTL leases.
        with FileLock(
            str(self.index.directory / f"{self.product.key}.lock"),
            timeout=self.settings.lock_timeout,
        ):
            records = candidates()
            local = self._local(records)
            if local:
                return local
            recovered = self._raw(records)
            if recovered:
                return recovered
            # Known records/raw/export state survive metadata TTL. Avoid another
            # lookup when the nearest suitable known frame can be recovered.
            if not records and not self.index.covered(self.product, start, end):
                self._event("jsoc_metadata_lookup")
                records_found = self.client.lookup(
                    self.product, target, self.settings.search_window_seconds
                )
                window = self.settings.search_window_seconds
                self.index.remember(
                    self.product,
                    records_found,
                    target.timestamp() - window,
                    target.timestamp() + window,
                    self.settings.metadata_ttl
                    if any(
                        not r.quality & self.product.quality_mask
                        and start <= r.utc.timestamp() <= end
                        for r in records_found
                    )
                    else self.settings.negative_ttl,
                )
                records = candidates()
            if not records:
                raise JSOCError(
                    "No suitable SDO observation within the requested tolerance"
                )
            record = records[0]
            return self._acquire(record, email)

    def _acquire(self, record, email):
        identity = record.identity(self.product)
        folder = self.paths.raw_source(self.product.directory)
        raw = folder / f"{identity}.fits"
        with raw_operation(folder, timeout=self.settings.lock_timeout) as operation:
            if raw.is_file():
                try:
                    return self._publish(record, raw, operation)
                except SDOValidationError:
                    self._event("sdo_raw_invalid")
                    # Retain failed quick/original for diagnosis; a new successful
                    # transfer will atomically replace it.
            # A known full-FITS export takes precedence over retrying a quick
            # path that previously produced incomplete scientific headers.
            full_export = self.index.latest_export(identity, "url")
            methods = (
                ("url_quick", "url")
                if self.settings.quick and not full_export
                else ("url",)
            )
            for method in methods:
                try:
                    self._obtain(record, method, raw, email)
                    return self._publish(record, raw, operation)
                except (SDOValidationError, ExportUnavailable) as exc:
                    saved = self.index.latest_export(identity, method)
                    if saved:
                        self.index.export_update(
                            saved["id"], status="invalid", error=type(exc).__name__
                        )
                    if method == "url":
                        raise JSOCError(
                            "JSOC scientific FITS validation/export failed"
                        ) from exc
                    self._event("jsoc_quick_fallback")
            raise JSOCError("No usable export")

    def _publish(self, record, raw, operation):
        solar_map, header = read_scientific_fits(raw)
        self._validate_record(solar_map, record)
        identity = record.identity(self.product)
        self.index.artifact_update(identity, raw_path=str(raw), status="downloaded")
        operation.remember(raw)
        self._event("sdo_validation")
        path = self.storage.write(self.product, record, solar_map, header)
        self.index.artifact_update(
            identity, map_path=str(path), checksum=sha256(path), status="published"
        )
        operation.verified = not self.settings.keep_fits
        self._event("sdo_published")
        return self.storage.read(path), self._provenance(record, path)

    def _obtain(self, record, method, raw, email):
        identity = record.identity(self.product)
        saved = self.index.latest_export(identity, method)
        if saved:
            if saved["status"] == "submitting":
                raise JSOCError(
                    "Ambiguous JSOC submission: inspect saved intent before retrying"
                )
            self._event("jsoc_existing_export_reused")
            try:
                urls = self._ready(saved)
                try:
                    self.client.download(urls[0], raw)
                except ExportUnavailable:
                    if not saved["remote_id"]:
                        raise
                    # Expired URL does not prove the export is gone. Refresh
                    # from its ID before permitting another submission.
                    saved["status"] = "pending"
                    saved["urls"] = None
                    urls = self._ready(saved)
                    self.client.download(urls[0], raw)
                return
            except ExportUnavailable:
                self.index.export_update(
                    saved["id"], status="unusable", error="expired_or_rejected"
                )
        key = self.index.reserve_export(identity, method, email)
        self._event(
            "jsoc_quick_download" if method == "url_quick" else "jsoc_new_export"
        )
        try:
            request = self.client.submit(
                f"{record.spec}{{{self.product.segment}}}", method, email
            )
        except ExportUnavailable:
            self.index.export_update(key, status="unusable", error="rejected")
            raise
        # A network exception leaves a durable ambiguous intent. Never blindly
        # submit twice after a crash or lost response.
        remote_id = request.id
        self.index.export_update(
            key, remote_id=remote_id, status="pending", checked=time.time()
        )
        status = self.client.state(request)
        self.index.export_update(
            key,
            remote_id=remote_id,
            status="ready" if status == 0 else "pending",
            checked=time.time(),
        )
        urls = self.client.urls(request) if status == 0 else None
        if urls:
            self.index.export_update(key, urls=urls)
        saved = self.index.latest_export(identity, method)
        urls = urls or self._ready(saved)
        self.client.download(urls[0], raw)

    def _ready(self, saved):
        deadline = time.monotonic() + self.settings.wait_timeout
        if saved["status"] == "ready" and saved["urls"]:
            return json.loads(saved["urls"])
        if not saved["remote_id"]:
            raise ExportUnavailable("No recoverable export ID")
        while True:
            delay = max(0, saved["checked"] + self.settings.poll_seconds - time.time())
            if time.monotonic() + delay > deadline:
                raise JSOCError("Export wait timed out; saved export can be resumed")
            if delay:
                time.sleep(delay)
            # Persist before polling so a crash/network outage cannot cause a
            # second worker to immediately repeat the same status request.
            saved["checked"] = time.time()
            saved["attempts"] += 1
            self.index.export_update(
                saved["id"], checked=saved["checked"], attempts=saved["attempts"]
            )
            try:
                request = self.client.restore(saved["remote_id"])
            except JSOCTransportError as exc:
                # Persist Retry-After across independent users and restarts.
                checked = max(
                    saved["checked"],
                    time.time() + exc.retry_after - self.settings.poll_seconds,
                )
                self.index.export_update(
                    saved["id"], checked=checked, error="temporary_http_failure"
                )
                raise
            status = self.client.state(request)
            if status == 0:
                urls = self.client.urls(request)
                self.index.export_update(saved["id"], status="ready", urls=urls)
                return urls
            self.index.export_update(saved["id"], status="pending")
            if time.monotonic() >= deadline:
                raise JSOCError("Export wait timed out; saved export can be resumed")
