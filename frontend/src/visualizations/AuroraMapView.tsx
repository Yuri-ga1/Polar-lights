import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { PathLayer, PolygonLayer } from "@deck.gl/layers";
import type { AuroraResult } from "../api/contracts";
import { apiClient } from "../api/client";
import { useWorkspace, type StyleSpec } from "../store";
import "maplibre-gl/dist/maplibre-gl.css";

maplibregl.setWorkerUrl(workerUrl);
type Sector = { polygon: number[][]; color: [number, number, number, number] };
type GeoPath = [number, number][];
export function auroraRadiusPixels(zoom: number, baseSize: number): number {
  return Math.max(2, Math.min(18, baseSize * 2 ** (zoom - 2)));
}
function sectors(
  result: AuroraResult,
  zoom: number,
  baseSize: number,
): Sector[] {
  const output: Sector[] = [];
  const radiusPixels = auroraRadiusPixels(zoom, baseSize);
  const longitudeRadius = (radiusPixels * 360) / (512 * 2 ** zoom);
  for (const point of result.observations) {
    const palette = point.sectorColors.map((hex) => {
      const value = hex.replace("#", "");
      return [
        parseInt(value.slice(0, 2), 16),
        parseInt(value.slice(2, 4), 16),
        parseInt(value.slice(4, 6), 16),
        240,
      ] as [number, number, number, number];
    });
    if (!palette.length) continue;
    palette.forEach((color, index) => {
      const start = (index * 360) / palette.length;
      const end = ((index + 1) * 360) / palette.length;
      const arc = Array.from({ length: 13 }, (_, i) => {
        const angle = ((start + ((end - start) * i) / 12) * Math.PI) / 180;
        const latitudeRadius =
          longitudeRadius * Math.cos((point.lat * Math.PI) / 180);
        return [
          point.lon + Math.cos(angle) * longitudeRadius,
          point.lat + Math.sin(angle) * latitudeRadius,
        ];
      });
      output.push({
        polygon: [[point.lon, point.lat], ...arc, [point.lon, point.lat]],
        color,
      });
    });
  }
  return output;
}

export default function AuroraMapView({
  result,
  style,
  chartId,
}: {
  result: AuroraResult;
  style: StyleSpec;
  chartId: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const overlay = useRef<MapboxOverlay | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [geomagneticLine, setGeomagneticLine] = useState<GeoPath[]>([]);
  const [currentZoom, setCurrentZoom] = useState(style.map.zoom);
  const observations = useMemo(
    () => sectors(result, currentZoom, style.map.pointSize),
    [result, currentZoom, style.map.pointSize],
  );
  const geomagneticLatitudesKey =
    style.map.auroraGeomagneticLatitudes.join(",");
  useEffect(() => {
    if (
      !ready ||
      !style.map.showAuroraGeomagnetic ||
      !geomagneticLatitudesKey
    ) {
      setGeomagneticLine([]);
      return;
    }
    const timestamp = result.metadata.timestamp;
    if (!timestamp) return;
    const controller = new AbortController();
    setGeomagneticLine([]);
    const timer = window.setTimeout(() => {
      void apiClient
        .auroraGeomagneticLines(
          timestamp,
          geomagneticLatitudesKey.split(",").map(Number),
          controller.signal,
        )
        .then((response) => {
          if (!controller.signal.aborted) {
            setGeomagneticLine(
              response.lines.flatMap((line) => line.paths) as GeoPath[],
            );
            setError("");
          }
        })
        .catch((cause: unknown) => {
          if (!controller.signal.aborted)
            setError(
              cause instanceof Error
                ? cause.message
                : "Could not load geomagnetic line",
            );
        });
    }, 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [
    ready,
    geomagneticLatitudesKey,
    result.metadata.timestamp,
    style.map.showAuroraGeomagnetic,
  ]);
  useEffect(() => {
    if (!host.current) return;
    let instance: maplibregl.Map | undefined;
    try {
      instance = new maplibregl.Map({
        container: host.current,
        center: [style.map.longitude, style.map.latitude],
        zoom: style.map.zoom,
        attributionControl: false,
        canvasContextAttributes: { preserveDrawingBuffer: true },
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
      map.current = instance;
      instance.on("zoom", () => setCurrentZoom(instance!.getZoom()));
      instance.on("moveend", (event) => {
        if (!event.originalEvent) return;
        const state = useWorkspace.getState();
        const chart = state.charts.find((item) => item.id === chartId);
        if (!chart) return;
        const center = instance!.getCenter();
        state.update(chartId, {
          styleSpec: {
            ...chart.styleSpec,
            map: {
              ...chart.styleSpec.map,
              longitude: center.lng,
              latitude: center.lat,
              zoom: instance!.getZoom(),
              bearing: instance!.getBearing(),
              pitch: instance!.getPitch(),
            },
          },
        });
      });
      const deck = new MapboxOverlay({ interleaved: false, layers: [] });
      overlay.current = deck;
      instance.addControl(deck);
      instance.addControl(
        new maplibregl.NavigationControl({ showCompass: false }),
        "top-right",
      );
      instance.on("load", () => setReady(true));
      instance.on("error", (event) => setError(event.error.message));
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Map initialization failed",
      );
    }
    return () => {
      instance?.remove();
      map.current = null;
      overlay.current = null;
    };
    // The map is scoped to this chart card; map style changes update it below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chartId]);
  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance) return;
    instance.jumpTo({
      center: [style.map.longitude, style.map.latitude],
      zoom: style.map.zoom,
      bearing: style.map.bearing,
      pitch: style.map.pitch,
    });
    instance.setLayoutProperty(
      "land",
      "visibility",
      style.map.coastline ? "visible" : "none",
    );
  }, [
    ready,
    style.map.longitude,
    style.map.latitude,
    style.map.zoom,
    style.map.bearing,
    style.map.pitch,
    style.map.coastline,
  ]);
  useEffect(() => {
    const instance = map.current;
    if (!ready || !instance) return;
    overlay.current?.setProps({
      layers: [
        new PolygonLayer<GeoPath>({
          id: `aurora-night-${chartId}`,
          data: style.map.showAuroraTerminator
            ? (result.overlays.nightPolygons as GeoPath[])
            : [],
          getPolygon: (ring) => ring,
          getFillColor: [77, 84, 94, 95],
          getLineColor: [77, 84, 94, 0],
          stroked: false,
          filled: true,
          pickable: false,
        }),
        new PolygonLayer<Sector>({
          id: `aurora-sectors-${chartId}`,
          data: observations,
          getPolygon: (sector) => sector.polygon,
          getFillColor: (sector) => sector.color,
          getLineColor: [25, 35, 45, 180],
          lineWidthMinPixels: 0.5,
          stroked: true,
          filled: true,
          opacity: style.map.opacity,
          pickable: false,
          updateTriggers: {
            getPolygon: [observations],
            getFillColor: [observations],
          },
        }),
        new PathLayer<GeoPath>({
          id: `aurora-geomagnetic-line-${chartId}`,
          data: style.map.showAuroraGeomagnetic ? geomagneticLine : [],
          getPath: (path) => path,
          getColor: [238, 142, 32, 220],
          getWidth: 1.5,
          widthUnits: "pixels",
          pickable: false,
        }),
        new PathLayer<GeoPath>({
          id: `aurora-terminator-${chartId}`,
          data: style.map.showAuroraTerminator
            ? (result.overlays.terminator as GeoPath[])
            : [],
          getPath: (path) => path,
          getColor: [20, 29, 41, 170],
          getWidth: 1.2,
          widthUnits: "pixels",
          pickable: false,
        }),
      ],
    });
  }, [
    chartId,
    geomagneticLine,
    observations,
    ready,
    result,
    style.map.opacity,
    style.map.showAuroraGeomagnetic,
    style.map.showAuroraTerminator,
  ]);
  return (
    <div className="map-shell">
      <div
        ref={host}
        className="map-canvas"
        role="img"
        aria-label={`Aurora observations map for ${result.metadata.timestamp || "selected date"}`}
      />
      <div className="map-legend aurora-legend" aria-label="Aurora">
        <span>
          <i className="aurora-legend-symbol" />
          Aurora
        </span>
      </div>
      <small className="map-meta">
        {result.observations.length} observations
        {result.metadata.timestamp ? ` · ${result.metadata.timestamp}` : ""}
      </small>
      {error && (
        <div className="map-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
