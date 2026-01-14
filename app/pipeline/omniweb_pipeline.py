from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable

from app.omniweb import OmniWebDownloader


def download_omniweb_day(
    day: date,
    output_dir: Path | str,
    variables: Iterable[str] | None = None,
    file_pattern: str | None = None,
) -> Path:
    downloader = OmniWebDownloader()
    return downloader.download_day(
        day=day,
        output_dir=output_dir,
        variables=variables,
        file_pattern=file_pattern,
    )
