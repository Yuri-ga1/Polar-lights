from __future__ import annotations

import re
from hashlib import sha256
from urllib.parse import urlencode
from uuid import uuid4

from app.base_classes.base_downloader import BaseDownloader
from app.logging_config import logged_stage
from app.simurg.gec_processor import GecProcessor
from app.storage.raw_retention import raw_locked


class GecDownloader(BaseDownloader):
    BASE_URL = "https://simurg.iszf.irk.ru/gen_file"

    def __init__(
        self, out_dir=".", sources=None, normalization="gec_tec", *, timeout=60
    ):
        if not isinstance(sources, (list, tuple)) or not sources:
            raise ValueError("sources must be a non-empty list of GIM names")
        self.sources = list(dict.fromkeys(sources))
        for value in [*self.sources, normalization]:
            if not isinstance(value, str) or not re.fullmatch(
                r"[a-z][a-z0-9_]*", value
            ):
                raise ValueError("Invalid GIM source or normalization name")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.normalization, self.timeout = normalization, timeout
        super().__init__(out_dir)

    @logged_stage("download")
    @raw_locked
    def download(self, start_year: int, end_year: int, *, refresh=False) -> str:
        if (
            type(start_year) is not int
            or type(end_year) is not int
            or not 1 <= start_year <= end_year <= 9999
        ):
            raise ValueError("Expected an ordered range of years")
        params = {
            "data": "gec",
            "type": "csv",
            "types": ",".join(self.sources),
            "syear": start_year,
            "eyear": end_year,
            "normalization": self.normalization,
        }
        # Keep arbitrary source lists out of filenames and filesystem limits.
        key = sha256(params["types"].encode()).hexdigest()[:16]
        filename = f"gec_{self.normalization}_{key}_{start_year}_{end_year}.csv"
        if refresh:
            # Failed/unprocessed raw responses must survive a refresh.
            filename = filename.removesuffix(".csv") + f"_{uuid4().hex}.csv"
        return self._download_result(
            f"{self.BASE_URL}?{urlencode(params)}",
            filename,
            timeout=self.timeout,
            validate_file=lambda path: GecProcessor(self.out_dir).load(
                path, self.sources
            ),
            retry_backoff=2,
            max_retry_delay=30,
            polling_interval=1,
            show_progress=False,
        )
