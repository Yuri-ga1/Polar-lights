from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict

from app.spaceweather import DstDownloader, GimDownloader, OmniWebDownloader


def download_spaceweather_day(
    target_date: date,
    base_dir: Path,
    trust_env: bool = False,
) -> Dict[str, Path]:
    """Download Dst, OMNIWeb, and GIM (UQRG) data for a single date."""
    base_dir = Path(base_dir)
    dst_dir = base_dir / "dst"
    omni_dir = base_dir / "omni"
    gim_dir = base_dir / "gim"

    dst_downloader = DstDownloader(base_dir=dst_dir, trust_env=trust_env)
    omni_downloader = OmniWebDownloader(base_dir=omni_dir, trust_env=trust_env)
    gim_downloader = GimDownloader(base_dir=gim_dir, trust_env=trust_env)

    dst_path = dst_downloader.download_day(target_date)
    omni_path = omni_downloader.download_day(target_date)
    gim_path = gim_downloader.download_day(target_date)

    return {
        "dst": dst_path,
        "omni": omni_path,
        "gim": gim_path,
    }
