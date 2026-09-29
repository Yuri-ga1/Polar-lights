import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ScatterplotLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import type { MapResult } from "../api/contracts";
import type { StyleSpec } from "../store";
import { bounds, color } from "./colors";
import "maplibre-gl/dist/maplibre-gl.css";
// Bundle the worker and its imports in both Vite development and production.
maplibregl.setWorkerUrl(workerUrl);
export default function MapView({
  result,
  style,
}: {
  result: MapResult;
  style: StyleSpec;
}) {
  const host = useRef<HTMLDivElement>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [hover, setHover] = useState<{
    lat: number;
    lon: number;
    value: number | null;
  } | null>(null);
  const range = useMemo(
    () => bounds(result.value, style),
    [result, style.vmin, style.vmax],
  );
  const indexes = useMemo(
    () => Array.from({ length: result.lat.length }, (_, i) => i),
    [result],
  );
  useEffect(() => {
    if (!host.current) return;
    let map: maplibregl.Map | undefined;
    let observer: ResizeObserver | undefined;
    try {
      map = new maplibregl.Map({
        container: host.current,
        center: [0, 45],
        zoom: 0.7,
        attributionControl: false,
        style: {
          version: 8,
          sources: { land: { type: "geojson", data: "/land.geojson" } },
          layers: [
            {
              id: "background",
              type: "background",
              paint: { "background-color": "#edf3f6" },
            },
            {
              id: "land",
              type: "fill",
              source: "land",
              paint: {
                "fill-color": "#d5e0e6",
                "fill-outline-color": "#a9becb",
              },
            },
          ],
        },
      });
      map.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "top-right",
      );
      const deck = new MapboxOverlay({ interleaved: false, layers: [] });
      overlay.current = deck;
      map.addControl(deck);
      map.on("load", () => setReady(true));
      map.on("error", (e) => setError(e.error.message));
      observer = new ResizeObserver(() => map?.resize());
      observer.observe(host.current);
    } catch (e) {
      setError(e instanceof Error ? e.message : "WebGL initialization failed");
    }
    return () => {
      observer?.disconnect();
      map?.remove();
      overlay.current = null;
    };
  }, []);
  useEffect(() => {
    setHover(null);
  }, [result]);
  useEffect(() => {
    overlay.current?.setProps({
      layers: [
        new ScatterplotLayer<number>({
          id: "scientific-points",
          data: indexes,
          pickable: true,
          getPosition: (i) => [result.lon[i], result.lat[i]],
          getRadius: 16000,
          radiusMinPixels: 3,
          radiusMaxPixels: 12,
          getFillColor: (i) =>
            result.value[i] == null
              ? [128, 128, 128, 160]
              : color(result.value[i]!, range[0], range[1], style.palette),
          updateTriggers: {
            getFillColor: [result, style.palette, ...range],
            getPosition: [result],
          },
          onHover: (info: PickingInfo<number>) =>
            setHover(
              info.index >= 0
                ? {
                    lat: result.lat[info.index],
                    lon: result.lon[info.index],
                    value: result.value[info.index],
                  }
                : null,
            ),
        }),
      ],
    });
  }, [indexes, result, style.palette, range, ready]);
  const units =
    typeof result.metadata.units === "string" ? result.metadata.units : "";
  return (
    <div
      className="map-view"
      data-testid="map-view"
      data-ready={ready}
      data-timestamp={result.metadata.timestamp}
    >
      <div ref={host} className="map-host" />
      {error && (
        <div role="alert" className="map-error">
          Map rendering: {error}
        </div>
      )}
      <div className="map-hud" aria-live="polite">
        {hover ? (
          <>
            lat {hover.lat.toFixed(2)} · lon {hover.lon.toFixed(2)}
            <br />
            {hover.value == null ? "missing_data" : hover.value.toFixed(3)}{" "}
            {units}
            <br />
            {result.metadata.timestamp}
          </>
        ) : (
          "Hover a point for coordinates and value"
        )}
      </div>
      {style.legend && (
        <div className="map-legend">
          <div
            style={{
              background: `linear-gradient(to right, ${[0, 0.25, 0.5, 0.75, 1]
                .map(
                  (t) =>
                    `rgba(${color(
                      range[0] + t * (range[1] - range[0]),
                      ...range,
                      style.palette,
                    )
                      .map((v, i) => (i === 3 ? v / 255 : v))
                      .join(",")})`,
                )
                .join(",")})`,
            }}
          />
          <span>
            {range[0].toPrecision(3)} — {range[1].toPrecision(3)} {units}
          </span>
        </div>
      )}
      <span className="map-attribution">Natural Earth · public domain</span>
    </div>
  );
}
