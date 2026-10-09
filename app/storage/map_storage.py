"""Append-only, timestamp-addressable storage for processed map slices."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import h5py

from app.storage.atomic import publish


class HDF5MapStorage:
    """Merge raw HDF5 ``data/<timestamp>`` datasets into one compact map file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def timestamps(self) -> set[str]:
        if not self.path.is_file():
            return set()
        with h5py.File(self.path, "r") as handle:
            return set(handle.get("data", {}).keys())

    def ingest(self, raw_path: str | Path) -> int:
        """Append previously unseen slices atomically enough for a single HDF5 file.

        Raw files are never altered.  If parsing fails, the existing processed
        map file stays intact because the destination is opened only after the
        source structure has been validated.
        """
        source = Path(raw_path)
        if not source.is_file() or source.stat().st_size == 0:
            return 0
        with h5py.File(source, "r") as input_handle:
            if "data" not in input_handle or not input_handle["data"].keys():
                return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        if self.path.exists():
            shutil.copy2(self.path, temporary)
            try:
                with h5py.File(source, "r") as input_handle, h5py.File(temporary, "r+") as output:
                    target = output.require_group("data")
                    added = self._copy_missing(target, input_handle["data"])
                publish(temporary, self.path)
                return added
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        with h5py.File(source, "r") as input_handle, h5py.File(temporary, "w") as output:
            added = self._copy_missing(output.create_group("data"), input_handle["data"])
        publish(temporary, self.path)
        return added

    def ingest_slices(self, slices: dict[datetime, object]) -> int:
        """Append parsed non-HDF5 map slices (for example IONEX/GIM) by UTC timestamp."""
        if not slices:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        if self.path.exists():
            shutil.copy2(self.path, temporary)
        try:
            with h5py.File(temporary, "a") as output:
                target = output.require_group("data")
                added = 0
                for timestamp, values in slices.items():
                    key = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if key not in target:
                        target.create_dataset(key, data=values, compression="gzip")
                        added += 1
            if temporary.exists():
                publish(temporary, self.path)
            return added
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _copy_missing(target, source_group) -> int:
        """Copy HDF5 datasets without materialising a multi-gigabyte file in RAM."""
        added = 0
        for key in source_group.keys():
            if key not in target:
                source_group.copy(key, target, name=key)
                added += 1
        return added
