"""Thin DRMS adapter. Only idempotent HTTP calls are retried automatically."""

import random
import time
from datetime import timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import requests
from astropy.time import Time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.solar.sdo import SDORecord


class JSOCTransportError(RuntimeError):
    """Bounded HTTP failure with URL/email removed from the public error."""

    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def retry_after_seconds(response):
    if response is None:
        return 0
    value = response.headers.get("Retry-After", "")
    try:
        return max(0, float(value))
    except ValueError:
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return 0


class ExportUnavailable(RuntimeError):
    """Server explicitly rejected an export or its download URL expired."""


class DRMSClient:
    def __init__(self, settings):
        import drms

        self.settings = settings
        self.client = drms.Client()
        self.session = requests.Session()
        self.submissions = requests.Session()
        retry = Retry(
            total=settings.retries - 1,
            backoff_factor=settings.backoff_seconds,
            backoff_jitter=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        for scheme in ("http://", "https://"):
            self.session.mount(scheme, HTTPAdapter(max_retries=retry))
        # drms 0.9.x's private adapter is isolated here and covered by an offline
        # contract test. Never patch module globals or log export URLs/emails.
        from types import SimpleNamespace
        from urllib.parse import parse_qs, urlsplit

        from drms.json import HttpJsonClient

        owner = self

        class BoundedJSONClient(HttpJsonClient):
            def _json_request(self, url):
                submission = parse_qs(urlsplit(url).query).get("op") == ["exp_request"]
                polling = parse_qs(urlsplit(url).query).get("op") == ["exp_status"]
                session = owner.submissions if submission or polling else owner.session
                try:
                    with session.get(url, timeout=settings.http_timeout) as response:
                        response.raise_for_status()
                        return SimpleNamespace(data=response.json())
                except (requests.RequestException, ValueError) as exc:
                    status = getattr(
                        getattr(exc, "response", None), "status_code", None
                    )
                    detail = type(exc).__name__
                    if status is not None:
                        detail += f" HTTP {status}"
                    host = urlsplit(url).hostname or "configured server"
                    raise JSOCTransportError(
                        f"JSOC request to {host} failed ({detail}); saved state retained",
                        retry_after_seconds(getattr(exc, "response", None)),
                    ) from None

        self.client._json = BoundedJSONClient(self.client._server)

    def lookup(self, product, target, window):
        start = Time(target - timedelta(seconds=window)).tai.strftime(
            "%Y.%m.%d_%H:%M:%S_TAI"
        )
        query = f"{product.series}[{start}/{2 * window:g}s]{product.selectors}"
        import drms

        try:
            keys, segments = self.client.query(
                query,
                key=f"{product.time_key},QUALITY",
                seg=product.segment,
                rec_index=True,
                convert_numeric=False,  # avoid DRMS auto-fetching series_struct
            )
        except drms.DrmsQueryError:
            raise JSOCTransportError("JSOC rejected the metadata lookup") from None
        records = []
        for spec, row in keys.iterrows():
            segment = segments.loc[spec, product.segment]
            if (
                not isinstance(segment, str)
                or not segment.strip()
                or segment.lower() in ("missing", "none")
            ):
                continue
            try:
                quality = int(str(row["QUALITY"]), 0)
            except ValueError:
                quality = int(row["QUALITY"])
            records.append(SDORecord(str(spec), str(row[product.time_key]), quality))
        return records

    def submit(self, spec, method, email):
        # No automatic retry: a lost response may have created a remote job.
        import drms

        try:
            return self.client.export(
                spec,
                method=method,
                protocol="as-is" if method == "url_quick" else "fits",
                email=email,
                n=1,
                filenamefmt=False,
            )
        except drms.DrmsExportError:
            raise ExportUnavailable("Export explicitly rejected") from None

    def restore(self, remote_id):
        import drms

        try:
            request = self.client.export_from_id(remote_id)
            if request.status == 6:
                raise ExportUnavailable("Export ID not found")
            return request
        except drms.DrmsExportError:
            raise ExportUnavailable("Export rejected or expired") from None

    @staticmethod
    def state(request):
        status = int(request.status)
        if status not in (0, 1, 2, 6):
            raise ExportUnavailable(f"JSOC export status {status}")
        return status

    @staticmethod
    def urls(request):
        # Exactly one selected record and segment; reject accidental bulk export.
        urls = request.urls
        if urls is None or len(urls) != 1:
            raise ExportUnavailable("Expected exactly one exported FITS")
        return [str(urls.iloc[0]["url"])]

    def download(self, url, destination):
        for attempt in range(self.settings.retries):
            try:
                return self._download_once(url, destination)
            except (requests.RequestException, OSError) as exc:
                if attempt + 1 == self.settings.retries:
                    raise JSOCTransportError(
                        "FITS transfer failed; saved export retained"
                    ) from None
                time.sleep(
                    max(
                        self.settings.backoff_seconds * 2**attempt + random.random(),
                        retry_after_seconds(getattr(exc, "response", None)),
                    )
                )

    def _download_once(self, url, destination):
        from app.storage.atomic import publish

        partial = destination.with_suffix(".fits.part")
        with self.session.get(
            url, stream=True, timeout=self.settings.http_timeout
        ) as response:
            if response.status_code in (401, 403, 404, 410):
                raise ExportUnavailable("Export URL is unavailable")
            response.raise_for_status()
            count = 0
            with open(partial, "wb") as handle:
                for chunk in response.iter_content(1024 * 1024):
                    count += len(chunk)
                    handle.write(chunk)
            if not count or (
                response.headers.get("Content-Length")
                and not response.headers.get("Content-Encoding")
                and count != int(response.headers["Content-Length"])
            ):
                raise OSError("Incomplete FITS download")
        publish(partial, destination)

    def close(self):
        self.session.close()
        self.submissions.close()
