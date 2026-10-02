import { useEffect, useMemo, useRef, useState } from "react";
import {
  Deck,
  OrthographicView,
  COORDINATE_SYSTEM,
  type PickingInfo,
} from "@deck.gl/core";
import { ScatterplotLayer, PathLayer, TextLayer } from "@deck.gl/layers";
import type { MapResult } from "../api/contracts";
import type { StyleSpec } from "../store";
import { bounds, styledColor } from "./colors";
import { Colorbar } from "./Colorbar";
import { useWorkspace } from "../store";
export function projectPolar(
  lon: number,
  lat: number,
  north: boolean,
  centralLongitude = 0,
): [number, number, number] {
  const radius = 90 - (north ? lat : -lat),
    angle = ((lon - centralLongitude) * Math.PI) / 180;
  return [
    radius * Math.sin(angle),
    radius * Math.cos(angle) * (north ? -1 : 1),
    0,
  ];
}
type Land = {
  features: {
    geometry: { type: string; coordinates: number[][][][] | number[][][] };
  }[];
};
export default function PolarMap({
  result,
  style,
  chartId,
}: {
  result: MapResult;
  style: StyleSpec;
  chartId: string;
}) {
  const host = useRef<HTMLDivElement>(null),
    deck = useRef<Deck<OrthographicView> | undefined>(undefined);
  const [ready, setReady] = useState(false),
    [hover, setHover] = useState<number | null>(null),
    [land, setLand] = useState<Land | null>(null),
    [error, setError] = useState("");
  const north = style.map.projection === "north-polar";
  const indices = useMemo(
    () =>
      result.lat
        .map((_, i) => i)
        .filter((i) => (north ? result.lat[i] >= 0 : result.lat[i] <= 0)),
    [result, north],
  );
  const range = useMemo(() => bounds(result.value, style), [result, style]);
  const initial = useRef(style.map);
  useEffect(() => setHover(null), [result, north]);
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/land.geojson", { signal: controller.signal })
      .then((r) => r.json())
      .then(setLand)
      .catch(() => {});
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!host.current) return;
    const canvas = document.createElement("canvas");
    host.current.append(canvas);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const instance = new Deck({
      canvas,
      parent: host.current,
      views: new OrthographicView({ flipY: false }),
      initialViewState: {
        target: [initial.current.polarX, initial.current.polarY, 0],
        zoom: initial.current.zoom,
      },
      onViewStateChange: ({ viewState }) => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          const s = useWorkspace.getState(),
            chart = s.charts.find((c) => c.id === chartId);
          if (!chart) return;
          const target = viewState.target ?? [0, 0, 0];
          s.update(chartId, {
            styleSpec: {
              ...chart.styleSpec,
              map: {
                ...chart.styleSpec.map,
                polarX: Math.max(-1000, Math.min(1000, target[0])),
                polarY: Math.max(-1000, Math.min(1000, target[1])),
                zoom: Math.max(
                  0,
                  Math.min(
                    10,
                    typeof viewState.zoom === "number" ? viewState.zoom : 0,
                  ),
                ),
              },
            },
          });
        }, 180);
      },
      controller: true,
      deviceProps: { webgl: { preserveDrawingBuffer: true } },
      onLoad: () => setReady(true),
      onError: (e) => setError(e.message),
      layers: [],
    });
    deck.current = instance;
    const observer = new ResizeObserver(() =>
      instance.setProps({
        width: host.current!.clientWidth,
        height: host.current!.clientHeight,
      }),
    );
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      clearTimeout(timer);
      instance.finalize();
      canvas.remove();
      deck.current = undefined;
    };
  }, [chartId]);
  useEffect(() => {
    deck.current?.setProps({
      initialViewState: {
        target: [style.map.polarX, style.map.polarY, 0],
        zoom: style.map.zoom,
      },
    });
  }, [style.map.polarX, style.map.polarY, style.map.zoom, ready]);
  useEffect(() => {
    const project = (p: number[]) =>
      projectPolar(p[0], p[1], north, style.map.longitude);
    const paths: number[][][] = [];
    if (style.map.graticule) {
      for (const lat of [0, 30, 60])
        paths.push(
          Array.from({ length: 73 }, (_, i) =>
            project([i * 5, north ? lat : -lat]),
          ),
        );
      for (let lon = 0; lon < 360; lon += 30)
        paths.push([project([lon, 0]), project([lon, north ? 90 : -90])]);
    }
    const coast: number[][][] = [];
    if (style.map.coastline && land)
      for (const f of land.features) {
        const rings =
          f.geometry.type === "Polygon"
            ? (f.geometry.coordinates as number[][][])
            : (f.geometry.coordinates as number[][][][]).flat();
        for (const ring of rings) {
          let part: number[][] = [];
          for (const point of ring) {
            if (north ? point[1] >= 0 : point[1] <= 0)
              part.push(project(point));
            else {
              if (part.length > 1) coast.push(part);
              part = [];
            }
          }
          if (part.length > 1) coast.push(part);
        }
      }
    deck.current?.setProps({
      layers: [
        new PathLayer({
          id: "coast",
          data: coast,
          getPath: (p) => p,
          getColor: [100, 125, 140, 200],
          getWidth: 1,
          widthUnits: "pixels",
          coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        }),
        new PathLayer({
          id: "grid",
          data: paths,
          getPath: (p) => p,
          getColor: [130, 150, 170, 120],
          getWidth: 1,
          widthUnits: "pixels",
          coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        }),
        new ScatterplotLayer<number>({
          id: "polar-samples",
          data: indices,
          coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
          getPosition: (i) => project([result.lon[i], result.lat[i]]),
          getRadius: style.map.pointSize,
          radiusUnits: "pixels",
          opacity: style.map.opacity,
          getFillColor: (i) => styledColor(result.value[i], ...range, style),
          pickable: true,
          onHover: (info: PickingInfo) =>
            setHover(info.index >= 0 ? indices[info.index] : null),
          updateTriggers: {
            getPosition: [result, north, style.map.longitude],
            getFillColor: [result, style],
          },
        }),
        new TextLayer({
          id: "labels",
          data: style.map.labels ? [0, 90, 180, 270] : [],
          getPosition: (lon) => project([lon, 5 * (north ? 1 : -1)]),
          getText: (lon) => `${lon}°`,
          getSize: style.labelSize,
          getColor: [55, 75, 100, 255],
          coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
        }),
      ],
    });
  }, [result, indices, style, north, land, range, ready]);
  const units =
    typeof result.metadata.units === "string" ? result.metadata.units : "";
  return (
    <div
      className="map-view"
      data-testid="map-view"
      data-ready={ready}
      data-projection={style.map.projection}
      data-timestamp={result.metadata.timestamp}
      style={{ background: style.background }}
    >
      <div ref={host} className="map-host" />
      <Colorbar style={style} range={range} units={units} />
      <div className="map-hud">
        {hover !== null
          ? `lat ${result.lat[hover].toFixed(2)} · lon ${result.lon[hover].toFixed(2)} · ${result.value[hover] ?? "missing_data"} ${units} · ${result.metadata.timestamp}`
          : `${north ? "North" : "South"} polar · hover a point`}
      </div>
      {!indices.length && (
        <span className="partial-label">No points in this hemisphere</span>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
