"""Deterministic full-world map specification and offline Chromium renderer."""

import hashlib
import json
import shutil
import tempfile
import zipfile
from importlib.metadata import version
from pathlib import Path

import numpy as np

from app.storage.atomic import publish

from .errors import BackendError
from .models import MapParameters

MAPLIBRE_VERSION = "5.6.1"
PLAYWRIGHT_VERSION = "1.55.0"


def spec_hash(spec):
    canonical = json.dumps(
        spec.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def asset_path(directory: Path, name: str):
    if name in ("world.js", "land.geojson"):
        return Path(__file__).parent / "render_assets" / name
    return directory / name


def frame_name(timestamp, product):
    return f"{timestamp.strftime('%Y-%m-%dT%H-%M-%SZ')}_{product}"


def asset_manifest(directory: Path):
    names = (
        "maplibre-gl.js",
        "maplibre-gl.css",
        "style.json",
        "world.js",
        "land.geojson",
    )
    if not all(asset_path(directory, name).is_file() for name in names):
        raise BackendError(
            "RENDER_NOT_CONFIGURED", "Install the pinned renderer assets first", 503
        )
    files = {
        name: hashlib.sha256(asset_path(directory, name).read_bytes()).hexdigest()
        for name in names
    }
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return {
        "assetVersion": hashlib.sha256(canonical.encode()).hexdigest(),
        "files": files,
        "maplibreVersion": MAPLIBRE_VERSION,
        "playwrightVersion": PLAYWRIGHT_VERSION,
        "dpr": 1,
        "fonts": [],
        "sprites": [],
        "glyphs": [],
        "tiles": [],
    }


def png_archive_chunks(path):
    """Filter legacy archives too, without changing stored job artifacts."""
    with tempfile.TemporaryFile() as output:
        with (
            zipfile.ZipFile(path) as source,
            zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target,
        ):
            for entry in source.infolist():
                if not entry.is_dir() and entry.filename.endswith(".png"):
                    with (
                        source.open(entry) as reader,
                        target.open(entry.filename, "w") as writer,
                    ):
                        shutil.copyfileobj(reader, writer)
        output.seek(0)
        while chunk := output.read(1024 * 1024):
            yield chunk


def render_maps(service, spec, directory, on_processing):
    from playwright.sync_api import sync_playwright

    assets = service.settings.render_assets
    manifest = asset_manifest(assets)
    if spec.assetVersion != manifest["assetVersion"]:
        raise BackendError(
            "INVALID_REQUEST", "Render asset version does not match", 409
        )
    if version("playwright") != PLAYWRIGHT_VERSION:
        raise BackendError(
            "RENDER_NOT_CONFIGURED", "Pinned Playwright version is required", 503
        )
    land = json.loads(asset_path(assets, "land.geojson").read_text(encoding="utf-8"))
    files = []
    # Remote generation yields before a browser is created.
    for timestamp in spec.timestamps:
        if not service.maps.has(spec.productId, timestamp):
            service.maps.acquire(spec.productId, timestamp)
    on_processing()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(
                viewport={"width": spec.width, "height": spec.height},
                device_scale_factor=spec.dpr,
                locale="en-US",
                timezone_id="UTC",
                reduced_motion="reduce",
            )
            page.route("**/*", lambda route: route.abort())
            page.set_content(
                '<html><body style="margin:0"><canvas id="map"></canvas></body></html>'
            )
            page.add_script_tag(path=str(asset_path(assets, "world.js")))
            for timestamp in spec.timestamps:
                on_processing()
                name = frame_name(timestamp, spec.productId)
                filename, metadata_name = name + ".png", name + ".json"
                try:
                    from PIL import Image

                    with Image.open(directory / filename) as existing:
                        existing.verify()
                    json.loads((directory / metadata_name).read_text())
                    files.extend([filename, metadata_name])
                    continue
                except (OSError, ValueError):
                    pass
                arrays, metadata = service.maps.read(
                    spec.productId,
                    MapParameters(timestamp=timestamp, resolution=spec.resolution),
                )
                on_processing()
                points = [
                    [
                        float(lon),
                        float(lat),
                        float(value) if np.isfinite(value) else None,
                    ]
                    for lon, lat, value in zip(
                        arrays["lon"], arrays["lat"], arrays["value"]
                    )
                    if np.isfinite(lon) and np.isfinite(lat)
                ]
                page.evaluate(
                    "input => window.drawWorld(document.getElementById('map'), input)",
                    {
                        "spec": spec.model_dump(mode="json"),
                        "points": points,
                        "land": land,
                        "title": name,
                        "units": metadata.get("units", ""),
                    },
                )
                page.locator("canvas").screenshot(
                    path=str(directory / (filename + ".tmp")), type="png", timeout=60000
                )
                publish(directory / (filename + ".tmp"), directory / filename)
                files.append(filename)
                (directory / (metadata_name + ".tmp")).write_text(
                    json.dumps(metadata, sort_keys=True), encoding="utf-8"
                )
                publish(directory / (metadata_name + ".tmp"), directory / metadata_name)
                files.append(metadata_name)
        finally:
            browser.close()
    (directory / "spec.tmp").write_text(
        json.dumps(
            {
                "spec": spec.model_dump(mode="json"),
                "specHash": spec_hash(spec),
                "assets": manifest,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    publish(directory / "spec.tmp", directory / "spec.json")
    files.append("spec.json")
    if len(spec.timestamps) > 1:
        on_processing()
        archive = "maps.zip"
        with zipfile.ZipFile(
            directory / (archive + ".tmp"), "w", compression=zipfile.ZIP_DEFLATED
        ) as bundle:
            for filename in files:
                if filename.endswith(".png"):
                    bundle.write(directory / filename, arcname=filename)
        publish(directory / (archive + ".tmp"), directory / archive)
        files.append(archive)
    return files
