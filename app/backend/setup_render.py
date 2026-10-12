"""Run explicitly: python -m app.backend.setup_render (requires network)."""

import hashlib
import json

import requests

from .config import Settings
from .render import MAPLIBRE_VERSION, asset_manifest

CHECKSUMS = {
    "maplibre-gl.js": "b5a34e6930ff937dbbb9eec8892cffb80ba473cce88ae5ca8c4654432f5f0ebc",
    "maplibre-gl.css": "792ac997dcf6ae6f643eb4e2dee4630c85e7056526bd8fb85ffe83c67d6c41b4",
}


def main():
    directory = Settings().render_assets
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("maplibre-gl.js", "maplibre-gl.css"):
        response = requests.get(
            f"https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/{name}", timeout=120
        )
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != CHECKSUMS[name]:
            raise RuntimeError(f"MapLibre {MAPLIBRE_VERSION} checksum mismatch: {name}")
        temporary = directory / f"{name}.tmp"
        temporary.write_bytes(response.content)
        temporary.replace(directory / name)
    # Explicitly empty external dependencies: this reproducible data-map style
    # has no text, sprites, fonts, glyphs or remotely changing basemap tiles.
    style = {
        "version": 8,
        "sources": {},
        "layers": [
            {
                "id": "background",
                "type": "background",
                "paint": {"background-color": "#eef2f6"},
            }
        ],
    }
    (directory / "style.json").write_text(
        json.dumps(style, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(asset_manifest(directory), indent=2))


if __name__ == "__main__":
    main()
