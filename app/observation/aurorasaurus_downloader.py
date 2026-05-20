from __future__ import annotations

from app.base_classes.base_downloader import BaseDownloader


class AurorasaurusDownloader(BaseDownloader):
    """Downloader for the Aurorasaurus Web Observations dataset."""

    DATASET_URL: str = (
        "https://zenodo.org/records/16783265/files/"
        "web_observations_2014-08-01_to_2025-08-02_cleaned.csv?download=1"
    )
    FILENAME: str = "web_observations_2014-08-01_to_2025-08-02_cleaned.csv"

    def __init__(self, out_dir: str = "files") -> None:
        super().__init__(out_dir=out_dir)

    def download(self, filename: str | None = None) -> str:
        """Download the dataset or return the cached local file path."""
        target_filename = filename or self.FILENAME
        existing_file = self._get_existing_file(target_filename, min_size_bytes=1024)
        if existing_file:
            return existing_file

        return self._download_result(
            url=self.DATASET_URL,
            filename=target_filename,
            timeout=120,
            verify=True,
            polling_interval=5,
            chunk_size=1024 * 1024,
        )
