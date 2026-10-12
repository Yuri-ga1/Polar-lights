"""Isolated scientific and software-WebGL smoke test for the built image."""

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import pyarrow as pa

from app.backend.config import Settings
from app.backend.models import (
    KeogramRequest,
    MapParameters,
    MapRenderSpec,
    SeriesRequest,
)
from app.backend.render import asset_manifest, render_maps
from app.backend.service import DataService

STAMP = "2024-01-01T00:00:00Z"


def fixtures(root):
    service = DataService(Settings(root=Path(root)))
    points = np.array(
        [(60.0, 10.0, 0.4), (65.0, -10.0, 0.8)],
        dtype=[("lat", "f4"), ("lon", "f4"), ("roti", "f4")],
    )
    with h5py.File(service.maps.directory("roti-map") / "fixture.h5", "w") as handle:
        handle.create_group("data").create_dataset(STAMP, data=points)
    service.storage.merge(pd.DataFrame({"datetime": [STAMP], "omni_bz": [-2.0]}))
    return service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--fixtures", type=Path)
    args = parser.parse_args()
    if args.fixtures:
        fixtures(args.fixtures)
        return
    # Fail early if native scientific dependencies cannot load.
    import aacgmv2  # noqa: F401
    import cartopy.crs  # noqa: F401
    import ionex  # noqa: F401
    import sunpy.map  # noqa: F401

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        service = fixtures(root)
        payload, media = service.maps.response(
            "roti-map", MapParameters(timestamp=STAMP)
        )
        assert media == "application/vnd.apache.arrow.stream"
        assert pa.ipc.open_stream(payload).read_all().num_rows == 2
        payload, _ = service.response(
            SeriesRequest(
                productId="omni",
                parameters={"start": STAMP, "end": STAMP, "columns": ["omni_bz"]},
            )
        )
        assert json.loads(payload)
        payload, _ = service.response(
            KeogramRequest(
                productId="roti-keogram", parameters={"start": STAMP, "end": STAMP}
            )
        )
        assert json.loads(payload)
        if not args.skip_browser:
            assets = service.settings.render_assets
            spec = MapRenderSpec(
                productId="roti-map",
                timestamps=(datetime(2024, 1, 1, tzinfo=UTC),),
                width=256,
                height=256,
                resolution="full",
                assetVersion=asset_manifest(assets)["assetVersion"],
            )
            output = root / "render"
            output.mkdir()
            render_maps(service, spec, output, lambda: None)
            from PIL import Image

            with Image.open(next(output.glob("*.png"))) as png:
                assert png.size == (256, 256)
                assert len(png.convert("RGB").getcolors(65536)) > 1
        print(
            "PASS: native imports, HDF5/Arrow, time series, keogram"
            + (
                ", offline Chromium/Canvas world-map PNG"
                if not args.skip_browser
                else " (browser skipped)"
            )
        )


if __name__ == "__main__":
    main()
