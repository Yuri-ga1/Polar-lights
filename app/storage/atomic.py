"""Publish a closed temporary artifact and persist its directory entry."""

import os
from pathlib import Path


def publish(source: str | Path, destination: str | Path) -> None:
    with open(source, "rb") as handle:
        os.fsync(handle.fileno())
    os.replace(source, destination)
    if os.name == "posix":
        descriptor = os.open(Path(destination).parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
