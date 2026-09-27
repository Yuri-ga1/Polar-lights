"""Run explicitly: python -m app.backend.setup_render (requires network)."""

import json

import requests

from .config import Settings
from .render import MAPLIBRE_VERSION, asset_manifest


def main():
    directory = Settings().render_assets
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("maplibre-gl.js", "maplibre-gl.css"):
        response = requests.get(
            f"https://unpkg.com/maplibre-gl@{MAPLIBRE_VERSION}/dist/{name}", timeout=120
        )
        response.raise_for_status()
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
