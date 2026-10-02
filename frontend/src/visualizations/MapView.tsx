import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ScatterplotLayer } from "@deck.gl/layers";
import type { PickingInfo } from "@deck.gl/core";
import type { MapResult } from "../api/contracts";
import type { StyleSpec } from "../store";
import { bounds, drawOrder, mapColor } from "./colors";
import { Colorbar } from "./Colorbar";
import { useWorkspace } from "../store";
import "maplibre-gl/dist/maplibre-gl.css";
// Vite emits MapLibre 6's bundled ESM worker for development and production.
maplibregl.setWorkerUrl(workerUrl);
const PolarMap = lazy(() => import("./PolarMap"));
type Props = {
  result: MapResult;
  style: StyleSpec;
  chartId: string;
  projectionAllowed: boolean;
};
export default function MapView(props: Props) {
  return props.projectionAllowed &&
    props.style.map.projection !== "geographic" ? (
    <Suspense fallback={<p>Loading polar view…</p>}>
      <PolarMap
        result={props.result}
        style={props.style}
        chartId={props.chartId}
      />
    </Suspense>
  ) : (
    <GeographicMap {...props} />
  );
}
function GeographicMap({ result, style, chartId }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const initial = useRef(style.map);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [hover, setHover] = useState<{
    lat: number;
    lon: number;
    value: number | null;
  } | null>(null);
  const range = useMemo(() => bounds(result.value, style), [result, style]);
  const indexes = useMemo(
    () => drawOrder(result.value, style.map.showNoData),
    [result.value, style.map.showNoData],
  );
  useEffect(() => {
    if (!host.current) return;
    let map: maplibregl.Map | undefined;
    let observer: ResizeObserver | undefined;
    try {
      map = new maplibregl.Map({
        container: host.current,
        center: [initial.current.longitude, initial.current.latitude],
        zoom: initial.current.zoom,
        canvasContextAttributes: { preserveDrawingBuffer: true },
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
      mapRef.current = map;
      map.on("moveend", (e) => {
        if (!e.originalEvent || !map) return;
        const s = useWorkspace.getState(),
          chart = s.charts.find((c) => c.id === chartId);
        if (!chart) return;
        const center = map.getCenter();
        s.update(chartId, {
          styleSpec: {
            ...chart.styleSpec,
            map: {
              ...chart.styleSpec.map,
              longitude: center.lng,
              latitude: center.lat,
              zoom: map.getZoom(),
              bearing: map.getBearing(),
              pitch: map.getPitch(),
            },
          },
        });
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
      mapRef.current = null;
    };
  }, [chartId]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.jumpTo({
      center: [style.map.longitude, style.map.latitude],
      zoom: style.map.zoom,
      bearing: style.map.bearing,
      pitch: style.map.pitch,
    });
    map.setLayoutProperty(
      "land",
      "visibility",
      style.map.coastline ? "visible" : "none",
    );
    map.setPaintProperty("background", "background-color", style.background);
    if (!map.getSource("graticule")) {
      const lines: number[][][] = [];
      for (let lat = -60; lat <= 60; lat += 30)
        lines.push(Array.from({ length: 73 }, (_, i) => [-180 + i * 5, lat]));
      for (let lon = -180; lon < 180; lon += 30)
        lines.push(Array.from({ length: 35 }, (_, i) => [lon, -85 + i * 5]));
      map.addSource("graticule", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: lines.map((coordinates) => ({
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates },
          })),
        },
      });
      map.addLayer({
        id: "graticule",
        type: "line",
        source: "graticule",
        paint: {
          "line-color": "#91a5b0",
          "line-opacity": 0.5,
          "line-width": 1,
        },
      });
    }
    map.setLayoutProperty(
      "graticule",
      "visibility",
      style.map.graticule ? "visible" : "none",
    );
  }, [style.map, style.background, ready]);
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
          getRadius: style.map.pointSize,
          radiusUnits: "pixels",
          opacity: style.map.opacity,
          getFillColor: (i) => mapColor(result.value[i], ...range, style),
          updateTriggers: {
            getFillColor: [result, style, ...range],
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
  }, [indexes, result, style, range, ready]);
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
      <Colorbar style={style} range={range} units={units} />
      {style.map.labels && (
        <span className="map-view-label">
          Geographic · {style.map.latitude.toFixed(1)}°,{" "}
          {style.map.longitude.toFixed(1)}°
        </span>
      )}
      <span className="map-attribution">Natural Earth · public domain</span>
    </div>
  );
}
