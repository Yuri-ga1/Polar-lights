from datetime import date
from pathlib import Path

from app.pipeline.spaceweather_pipeline import download_spaceweather_day


if __name__ == "__main__":
    target_date = date(2025, 11, 12)
    base_dir = Path("files") / "spaceweather"
    paths = download_spaceweather_day(target_date, base_dir)

    for key, path in paths.items():
        print(f"{key}: {path}")
