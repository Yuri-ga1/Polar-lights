import { useEffect, useState } from "react";
import { apiClient } from "../api/client";
import type { StyleSpec } from "../store";

export type GeoPath = [number, number][];

export function useMapOverlays(
  timestamp: string | undefined,
  map: StyleSpec["map"],
) {
  const [geomagnetic, setGeomagnetic] = useState<GeoPath[]>([]);
  const [solar, setSolar] = useState<{
    terminator: GeoPath[];
    nightPolygons: GeoPath[];
  }>({ terminator: [], nightPolygons: [] });
  const [geomagneticError, setGeomagneticError] = useState("");
  const [terminatorError, setTerminatorError] = useState("");
  const latitudes = map.auroraGeomagneticLatitudes.join(",");
  useEffect(() => {
    setGeomagnetic([]);
    setGeomagneticError("");
    if (!timestamp || !map.showAuroraGeomagnetic || !latitudes) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void apiClient
        .auroraGeomagneticLines(
          timestamp,
          latitudes.split(",").map(Number),
          controller.signal,
        )
        .then((response) => {
          if (!controller.signal.aborted)
            setGeomagnetic(response.lines.flatMap((line) => line.paths));
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted)
            setGeomagneticError(
              error instanceof Error
                ? error.message
                : "Could not load geomagnetic lines",
            );
        });
    }, 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [timestamp, map.showAuroraGeomagnetic, latitudes]);
  useEffect(() => {
    setSolar({ terminator: [], nightPolygons: [] });
    setTerminatorError("");
    if (!timestamp || !map.showAuroraTerminator) return;
    const controller = new AbortController();
    void apiClient
      .mapOverlays(timestamp, controller.signal)
      .then((paths) => {
        if (!controller.signal.aborted) setSolar(paths);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setTerminatorError(
            error instanceof Error
              ? error.message
              : "Could not load solar terminator",
          );
      });
    return () => controller.abort();
  }, [timestamp, map.showAuroraTerminator]);
  return {
    geomagnetic: map.showAuroraGeomagnetic ? geomagnetic : [],
    terminator: map.showAuroraTerminator ? solar.terminator : [],
    nightPolygons: map.showAuroraTerminator ? solar.nightPolygons : [],
    error: geomagneticError || terminatorError,
  };
}

// Split at the equator so polar paths never connect across the hidden hemisphere.
export function clipHemisphere(paths: GeoPath[], north: boolean): GeoPath[] {
  const clipped: GeoPath[] = [];
  for (const path of paths) {
    let part: GeoPath = [];
    for (let i = 0; i < path.length; i++) {
      const point = path[i];
      const previous = path[i - 1];
      const visible = north ? point[1] >= 0 : point[1] <= 0;
      if (
        previous &&
        visible !== (north ? previous[1] >= 0 : previous[1] <= 0)
      ) {
        const t = -previous[1] / (point[1] - previous[1]);
        const edge: [number, number] = [
          previous[0] + t * (point[0] - previous[0]),
          0,
        ];
        if (visible) part = [edge];
        else {
          part.push(edge);
          if (part.length > 1) clipped.push(part);
          part = [];
        }
      }
      if (visible) part.push(point);
    }
    if (part.length > 1) clipped.push(part);
  }
  return clipped;
}

// Clip a filled ring against the equator, preserving the boundary that closes it.
// Densify edges before polar projection: an equator edge must follow the rim,
// rather than a straight chord through the hemisphere.
export function clipNightPolygon(ring: GeoPath, north: boolean): GeoPath {
  const clipped: GeoPath = [];
  for (let i = 0; i < ring.length; i++) {
    const point = ring[i];
    const previous = ring[(i + ring.length - 1) % ring.length];
    const inside = north ? point[1] >= 0 : point[1] <= 0;
    const wasInside = north ? previous[1] >= 0 : previous[1] <= 0;
    if (inside !== wasInside) {
      const t = -previous[1] / (point[1] - previous[1]);
      clipped.push([previous[0] + t * (point[0] - previous[0]), 0]);
    }
    if (inside) clipped.push(point);
  }
  if (clipped.length < 3) return [];
  const dense: GeoPath = [];
  for (let i = 0; i < clipped.length; i++) {
    const a = clipped[i],
      b = clipped[(i + 1) % clipped.length];
    const steps = Math.max(
      1,
      Math.ceil(Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])) / 2),
    );
    for (let j = 0; j < steps; j++)
      dense.push([
        a[0] + ((b[0] - a[0]) * j) / steps,
        a[1] + ((b[1] - a[1]) * j) / steps,
      ]);
  }
  return dense;
}

// Independent segments avoid join/cap artifacts from path tessellation.
export function lineSegments<T>(paths: readonly (readonly T[])[]): [T, T][] {
  return paths.flatMap((path) =>
    path.slice(1).map((point, i): [T, T] => [path[i], point]),
  );
}
