from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Optional, TextIO, Union
import io
import gzip
import bz2
import lzma
import zipfile
import traceback

import numpy as np
from numpy.typing import NDArray
from app.base_classes.base_processor import BaseProcessor

import ionex


MAP_DTYPE = np.dtype([("lat", "float"), ("lon", "float"), ("vals", "float")])


@dataclass(frozen=True)
class GimGrid:
    """Grid metadata extracted from IONEX."""
    lat_grid: NDArray
    lon_grid: NDArray


class GimProcessor(BaseProcessor):
    """
    Local processor for GIM/IONEX files (e.g. uqrg3160.25i).

    Returns:
    - dict[datetime, NDArray] if file exists and parsed successfully
    - None if file missing/empty/unparseable

    NDArray values are flat structured arrays with dtype MAP_DTYPE: (lat, lon, vals).
    """

    def __init__(self, folder_path: str | Path, gim_type: str = "uqrg") -> None:
        super().__init__(folder_path)
        self.gim_type = gim_type.lower()

    # -------------------------
    # Helpers: date/time / name
    # -------------------------

    @staticmethod
    def _normalize_time(value: datetime) -> datetime:
        return value.replace(tzinfo=value.tzinfo or timezone.utc)

    @staticmethod
    def _coerce_date(value: Union[str, date, datetime]) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return datetime.strptime(value, "%Y-%m-%d").date()

    @staticmethod
    def _build_filename(target_date: date, gim_type: str) -> str:
        # IONEX naming like uqrg3160.25i
        doy = target_date.timetuple().tm_yday
        yy = target_date.year % 100
        session = 0
        return f"{gim_type}{doy:03d}{session}.{yy:02d}i"

    def _find_file(self, target_date: date) -> Optional[Path]:
        if not self.folder_path.exists():
            return None

        # Prefer exact expected filename first
        exact = self.folder_path / self._build_filename(target_date, self.gim_type)
        if exact.exists() and exact.stat().st_size > 0:
            return exact

        # Fallback glob: any matching file for day/year
        doy = target_date.timetuple().tm_yday
        yy = target_date.year % 100

        patterns = [
            f"{self.gim_type}{doy:03d}*.{yy:02d}i",
            f"{self.gim_type}{doy:03d}*.{yy:02d}i.*",
        ]
        matches: list[Path] = []
        for p in patterns:
            matches.extend(sorted(self.folder_path.glob(p)))

        for m in matches:
            if m.exists() and m.stat().st_size > 0:
                return m

        return None

    # -------------------------
    # Helpers: open as text
    # -------------------------

    @staticmethod
    def _open_ionex_text(path: Path) -> TextIO:
        """
        Open IONEX as text regardless of compression:
        - plain text
        - gzip (.gz)
        - zip (.zip) -> reads first file inside archive
        - bzip2 (.bz2)
        - xz (.xz)
        - Unix compress (.Z) -> requires system `uncompress`
        """
        with open(path, "rb") as f:
            head = f.read(6)

        # gzip magic: 1f 8b
        if head[:2] == b"\x1f\x8b":
            return gzip.open(path, "rt", encoding="utf-8", errors="ignore")

        # zip magic: PK
        if head[:2] == b"PK":
            zf = zipfile.ZipFile(path)
            names = sorted([n for n in zf.namelist() if not n.endswith("/")])
            if not names:
                raise ValueError(f"ZIP archive is empty: {path}")
            return io.TextIOWrapper(zf.open(names[0], "r"), encoding="utf-8", errors="ignore")

        # bzip2 magic: BZh
        if head[:3] == b"BZh":
            return bz2.open(path, "rt", encoding="utf-8", errors="ignore")

        # xz magic: fd 37 7a 58 5a 00
        if head[:6] == b"\xfd7zXZ\x00":
            return lzma.open(path, "rt", encoding="utf-8", errors="ignore")

        # Unix compress (.Z): typically 1f 9d or 1f a0
        if head[:2] in (b"\x1f\x9d", b"\x1f\xa0"):
            import subprocess

            p = subprocess.Popen(
                ["uncompress", "-c", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if p.stdout is None:
                raise RuntimeError("Failed to open subprocess stdout for uncompress")
            return io.TextIOWrapper(p.stdout, encoding="utf-8", errors="ignore")

        return open(path, "rt", encoding="utf-8", errors="ignore")

    # -------------------------
    # Parsing
    # -------------------------

    @staticmethod
    def _ionex_maps_to_structured(handle: TextIO) -> Dict[datetime, NDArray]:
        """
        Convert ionex.reader output to:
        key = epoch (UTC)
        value = flat structured array (lat, lon, tec)
        """
        data: Dict[datetime, NDArray] = {}

        for ionex_map in ionex.reader(handle):
            lats = ionex_map.grid.latitude
            lons = ionex_map.grid.longitude

            lon_grid = np.arange(lons.lon1, lons.lon2 + lons.dlon, lons.dlon)
            lat_grid = np.arange(lats.lat1, lats.lat2 + lats.dlat, lats.dlat)

            tec_iter = iter(ionex_map.tec)
            rows = []
            for lat in lat_grid:
                for lon in lon_grid:
                    rows.append((float(lat), float(lon), float(next(tec_iter))))

            epoch = GimProcessor._normalize_time(ionex_map.epoch.replace(tzinfo=timezone.utc))
            data[epoch] = np.array(rows, dtype=MAP_DTYPE)

        return data

    # -------------------------
    # Public API
    # -------------------------

    def load(self, date_value: Union[str, date, datetime]) -> Optional[Dict[datetime, NDArray]]:
        target_date = self._coerce_date(date_value)
        file_path = self._find_file(target_date)

        if not self._is_non_empty_file(file_path):
            print(f"File does not exist or empty: {file_path}")
            return None

        try:
            with self._open_ionex_text(file_path) as handle:
                text = handle.read()

            if "IONEX VERSION / TYPE" not in text[:200]:
                print(f"Not an IONEX text file: {file_path}")
                return None

            return self._ionex_maps_to_structured(io.StringIO(text)) or None

        except Exception:
            print(traceback.format_exc())
            return None

