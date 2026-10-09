import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchApi, url } from "../api/client";
import {
  renderApi,
  renderSpecSchema,
  type RenderSpec,
} from "../api/renderJobs";
import { useWorkspace, type ChartSpec } from "../store";
import {
  cancelRender,
  resumeRender,
  startRender,
  useRenderTasks,
} from "../renderTasks";
import { Numeric, Field } from "./Controls";
function PinnedPreview({
  chart,
  spec,
}: {
  chart: ChartSpec;
  spec: RenderSpec;
}) {
  const result = useWorkspace((s) => s.runtime[chart.id]?.result);
  const [document, setDocument] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    if (result?.dataType !== "map") return;
    void (async () => {
      try {
        const style = await (
          await fetchApi("/api/v1/render-assets/style.json", {
            signal: controller.signal,
          })
        ).json();
        const points = result.lat.flatMap((lat, i) =>
          result.value[i] == null
            ? []
            : [[result.lon[i], lat, result.value[i]]],
        );
        const data = JSON.stringify({ style, spec, points }).replaceAll(
          "<",
          "\\u003c",
        );
        setDocument(
          `<!doctype html><html><head><link rel="stylesheet" href="${url("/api/v1/render-assets/maplibre-gl.css")}"></head><body style="margin:0"><div id="map" style="width:100vw;height:100vh"></div><script src="${url("/api/v1/render-assets/maplibre-gl.js")}"></script><script>const input=${data};if(maplibregl.getVersion()!==input.spec.maplibreVersion)throw Error('MapLibre version mismatch');const map=new maplibregl.Map({container:'map',style:input.style,center:input.spec.center,zoom:input.spec.zoom,interactive:false,attributionControl:false});map.on('load',()=>{map.addSource('samples',{type:'geojson',data:{type:'FeatureCollection',features:input.points.map(p=>({type:'Feature',geometry:{type:'Point',coordinates:p.slice(0,2)},properties:{value:p[2]}}))}});map.addLayer({id:'samples',type:'circle',source:'samples',paint:{'circle-radius':2,'circle-opacity':1,'circle-color':['interpolate',['linear'],['get','value'],input.spec.minimum,'#2468db',input.spec.maximum,'#ef3024']}})});</script></body></html>`,
        );
      } catch {
        if (!controller.signal.aborted)
          setError("Pinned render preview is unavailable.");
      }
    })();
    return () => controller.abort();
  }, [result, spec]);
  return error ? (
    <p role="alert">{error}</p>
  ) : (
    <iframe
      title="Pinned server renderer preview"
      sandbox="allow-scripts allow-same-origin"
      srcDoc={document}
      style={{ width: "100%", height: 210, border: 0 }}
    />
  );
}
export function BatchRender({ chart }: { chart: ChartSpec }) {
  useEffect(() => {
    resumeRender(chart.id);
  }, [chart.id]);
  const assets = useQuery({
    queryKey: ["render-assets"],
    queryFn: ({ signal }) => renderApi.assets(signal),
    retry: false,
  });
  const [timestamps, setTimestamps] = useState(
      String(chart.dataSpec.timestamp ?? ""),
    ),
    [width, setWidth] = useState(1200),
    [height, setHeight] = useState(700),
    [minimum, setMinimum] = useState(0),
    [maximum, setMaximum] = useState(1),
    [error, setError] = useState(""),
    [preview, setPreview] = useState<RenderSpec | null>(null);
  const task = useRenderTasks((s) => s.tasks[chart.id]);
  const busy =
    task &&
    [
      "queued",
      "downloading",
      "processing",
      "waiting_external",
      "retrying",
    ].includes(task.status);
  const spec = () =>
    renderSpecSchema.parse({
      productId: chart.productId,
      timestamps: timestamps.split(/[\s,]+/).filter(Boolean),
      width,
      height,
      center: [chart.styleSpec.map.longitude, chart.styleSpec.map.latitude],
      zoom: chart.styleSpec.map.zoom,
      minimum,
      maximum,
      resolution: chart.dataSpec.resolution ?? "full",
      assetVersion: assets.data?.assetVersion,
      maplibreVersion: assets.data?.maplibreVersion,
      playwrightVersion: assets.data?.playwrightVersion,
      dpr: 1,
    });
  return (
    <details className="batch-render">
      <summary>Server map series</summary>
      <p className="hint">
        Server series uses its fixed blue/red palette and geographic camera. Use
        card export to retain custom appearance. Maximum 48 frames across three
        calendar dates.
      </p>
      {assets.error ? (
        <p role="alert">
          Render assets are not configured or do not match the supported pinned
          versions. See the setup guide.
        </p>
      ) : (
        <>
          <Field label="Render timestamps (UTC, one per line)">
            <textarea
              value={timestamps}
              onChange={(e) => setTimestamps(e.target.value)}
            />
          </Field>
          <Numeric
            label="Render width"
            value={width}
            min={256}
            max={2400}
            onChange={(v) => v && setWidth(v)}
          />
          <Numeric
            label="Render height"
            value={height}
            min={256}
            max={1600}
            onChange={(v) => v && setHeight(v)}
          />
          <Numeric
            label="Render minimum"
            value={minimum}
            onChange={(v) => v !== undefined && setMinimum(v)}
          />
          <Numeric
            label="Render maximum"
            value={maximum}
            onChange={(v) => v !== undefined && setMaximum(v)}
          />
          <button
            disabled={!assets.data || Boolean(busy)}
            onClick={() => {
              try {
                const s = spec();
                setError("");
                void startRender(chart.id, s);
              } catch {
                setError(
                  "Check timestamps, dimensions and color bounds before submitting.",
                );
              }
            }}
          >
            {task?.status === "failed" || task?.status === "cancelled"
              ? "Retry render"
              : "Render series"}
          </button>
          <button
            disabled={!assets.data}
            onClick={() => {
              try {
                setPreview(spec());
                setError("");
              } catch {
                setError("Complete the render specification first.");
              }
            }}
          >
            Preview pinned renderer
          </button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {busy && (
        <button onClick={() => cancelRender(chart.id)}>Cancel render</button>
      )}
      {preview && (
        <>
          <small>
            Preview uses the currently loaded frame and the backend’s exact
            MapLibre assets.
          </small>
          <PinnedPreview chart={chart} spec={preview} />
        </>
      )}
      {task && (
        <div role="status" aria-label="Render status">
          {task.status === "waiting_external"
            ? "Waiting for SIMuRG generation"
            : task.status}
          {task.error && <p role="alert">{task.error}</p>}
          {task.requestId && <code>Request ID: {task.requestId}</code>}
          {task.files && (
            <ul>
              {task.files.files.map((f) => (
                <li key={f.name}>
                  <a
                    href={url(f.url)}
                    download={f.name}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {f.name}
                  </a>
                </li>
              ))}
            </ul>
          )}
          <details>
            <summary>Submitted specification</summary>
            <pre>{JSON.stringify(task.spec, null, 2)}</pre>
          </details>
        </div>
      )}
    </details>
  );
}
