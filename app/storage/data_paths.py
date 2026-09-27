"""Canonical locations for local Polar Lights data.

Raw source responses, normalized tabular data and multidimensional map data
must not be mixed with date-specific working directories. Keeping this object
at the storage boundary prevents every pipeline from inventing paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @classmethod
    def from_root(cls, root: str | Path = "files") -> "DataPaths":
        return cls(Path(root))

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def maps(self) -> Path:
        return self.root / "maps"

    def raw_source(self, source: str) -> Path:
        path = self.raw / source
        path.mkdir(parents=True, exist_ok=True)
        return path

    def processed_file(self, source: str) -> Path:
        self.processed.mkdir(parents=True, exist_ok=True)
        return self.processed / f"{source}.csv"

    def map_file(self, product: str) -> Path:
        return self.map_dir(product) / f"{product}.h5"

    def map_dir(self, product: str) -> Path:
        """Directory for original multi-slice map files; filenames stay intact."""
        path = self.maps / product
        path.mkdir(parents=True, exist_ok=True)
        return path
