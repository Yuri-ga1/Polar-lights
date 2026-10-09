"""Deterministic MapLibre render specification and offline Chromium renderer."""

import hashlib
import json
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


def asset_manifest(directory: Path):
    names = ("maplibre-gl.js", "maplibre-gl.css", "style.json")
    if not all((directory / name).is_file() for name in names):
        raise BackendError(
            "RENDER_NOT_CONFIGURED", "Install the pinned renderer assets first", 503
        )
    files = {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
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
    style = json.loads((assets / "style.json").read_text(encoding="utf-8"))
    files = []
    # Remote generation yields before a browser is created.
    for timestamp in spec.timestamps:
        if not service.maps.has(spec.productId, timestamp):
            service.maps.acquire(spec.productId, timestamp)
    on_processing()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
        )
        try:
            page = browser.new_page(
                viewport={"width": spec.width, "height": spec.height},
                device_scale_factor=spec.dpr,
                locale="en-US",
                timezone_id="UTC",
                reduced_motion="reduce",
            )
            # The pinned default style has no remote assets. Never fetch a
            # URL provided through render input or allow browser network I/O.
            page.route("**/*", lambda route: route.abort())
            page.set_content(
                '<html><head></head><body style="margin:0"><div id="map" style="width:100vw;height:100vh"></div></body></html>'
            )
            page.add_style_tag(path=str(assets / "maplibre-gl.css"))
            page.add_script_tag(path=str(assets / "maplibre-gl.js"))
            if page.evaluate("maplibregl.getVersion()") != MAPLIBRE_VERSION:
                raise BackendError(
                    "RENDER_NOT_CONFIGURED", "MapLibre asset version mismatch", 503
                )
            page.evaluate(
                """async ({style, center, zoom}) => {
                window.map = new maplibregl.Map({container:'map', style, center, zoom,
                    interactive:false, attributionControl:false, fadeDuration:0, preserveDrawingBuffer:true});
                await new Promise((resolve, reject) => {
                    map.once('load', resolve); map.once('error', e => reject(e.error));
                });
            }""",
                {"style": style, "center": spec.center, "zoom": spec.zoom},
            )
            for number, timestamp in enumerate(spec.timestamps):
                filename = f"map-{number:04d}.png"
                metadata_name = f"map-{number:04d}.json"
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
                valid = np.isfinite(arrays["value"])
                points = [
                    [float(lon), float(lat), float(value)]
                    for lon, lat, value in zip(
                        arrays["lon"][valid],
                        arrays["lat"][valid],
                        arrays["value"][valid],
                    )
                ]
                page.evaluate(
                    """async ({points, minimum, maximum}) => {
                    const data = {type:'FeatureCollection', features:points.map(p => ({type:'Feature',
                        geometry:{type:'Point',coordinates:p.slice(0,2)},properties:{value:p[2]}}))};
                    if (map.getLayer('samples')) map.removeLayer('samples');
                    if (map.getSource('samples')) map.removeSource('samples');
                    map.addSource('samples', {type:'geojson',data});
                    map.addLayer({id:'samples',type:'circle',source:'samples',paint:{
                        'circle-radius':2,'circle-opacity':1,
                        'circle-color':['interpolate',['linear'],['get','value'],minimum,'#2468db',maximum,'#ef3024']}});
                    await new Promise(resolve => {map.once('idle',resolve); map.triggerRepaint();});
                }""",
                    {
                        "points": points,
                        "minimum": spec.minimum,
                        "maximum": spec.maximum,
                    },
                )
                filename = f"map-{number:04d}.png"
                page.screenshot(
                    path=str(directory / (filename + ".tmp")), type="png", animations="disabled", timeout=60000
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
    return [*files, "spec.json"]
