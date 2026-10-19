import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchApi } from "../api/client";
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
import { bounds, styledScale } from "../visualizations/colors";
import {
  rangeTimestamps,
  renderSteps,
  type RenderRange,
} from "../renderRanges";
import { Numeric, Field } from "./Controls";

function PinnedPreview({
  chart,
  spec,
}: {
  chart: ChartSpec;
  spec: RenderSpec;
}) {
  const result = useWorkspace((s) => s.runtime[chart.id]?.result);
  const timestamp = result?.metadata.timestamp;
  const matchingFrame =
    result?.dataType === "map" &&
    typeof timestamp === "string" &&
    spec.timestamps.some(
      (selected) => Date.parse(selected) === Date.parse(timestamp),
    );
  const [document, setDocument] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    if (result?.dataType !== "map" || !matchingFrame) return;
    void (async () => {
      try {
        const [script, land] = await Promise.all([
          fetchApi("/api/v1/render-assets/world.js", {
            signal: controller.signal,
          }).then((r) => r.text()),
          fetchApi("/api/v1/render-assets/land.geojson", {
            signal: controller.signal,
          }).then((r) => r.json()),
        ]);
        const points = result.lat.map((lat, i) => [
          result.lon[i],
          lat,
          result.value[i],
        ]);
        const data = JSON.stringify({
          spec,
          points,
          land,
          title: `${new Date(timestamp!).toISOString().slice(0, 19).replaceAll(":", "-")}Z_${chart.productId}`,
          units: result.metadata.units,
        }).replaceAll("<", "\\u003c");
        setDocument(
          `<!doctype html><html><body style="margin:0"><canvas style="width:100%;height:auto" id="map"></canvas><script>${script}</script><script>drawWorld(document.getElementById('map'),${data});</script></body></html>`,
        );
        setError("");
      } catch {
        if (!controller.signal.aborted)
          setError("Render preview is unavailable.");
      }
    })();
    return () => controller.abort();
  }, [result, spec, chart.productId, matchingFrame, timestamp]);
  if (result?.dataType !== "map")
    return <p>Load a map to preview its appearance.</p>;
  if (!matchingFrame)
    return (
      <p>Load one of the selected UTC frames to preview the batch renderer.</p>
    );
  return error ? (
    <p role="alert">{error}</p>
  ) : (
    <iframe
      title="Server renderer preview"
      sandbox="allow-scripts"
      srcDoc={document}
      style={{
        width: "100%",
        aspectRatio: `${spec.width}/${spec.height}`,
        border: 0,
      }}
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
  const initial = String(chart.dataSpec.timestamp ?? "")
    .replace(/Z$/, "")
    .slice(0, 19);
  const [ranges, setRanges] = useState<RenderRange[]>([
    { start: initial, end: initial },
  ]);
  const [step, setStep] = useState(30),
    [width, setWidth] = useState(1200),
    [height, setHeight] = useState(700);
  const [error, setError] = useState(""),
    [preview, setPreview] = useState<RenderSpec | null>(null);
  const [downloading, setDownloading] = useState(false);
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
  let timestamps: string[] = [],
    rangeError = "";
  try {
    timestamps = rangeTimestamps(ranges, step);
  } catch (e) {
    rangeError = (e as Error).message;
  }
  const spec = () => {
    if (rangeError) throw Error(rangeError);
    const s = chart.styleSpec,
      m = s.map;
    const [minimum, maximum] = bounds([], s);
    return renderSpecSchema.parse({
      productId: chart.productId,
      timestamps,
      width,
      height,
      center: [0, 0],
      zoom: 0,
      minimum,
      maximum,
      resolution: chart.dataSpec.resolution ?? "full",
      assetVersion: assets.data?.assetVersion,
      maplibreVersion: assets.data?.maplibreVersion,
      playwrightVersion: assets.data?.playwrightVersion,
      dpr: 1,
      appearance: {
        background: s.background,
        font: s.font,
        fontSize: s.fontSize,
        labelSize: s.labelSize,
        subtitle: s.subtitle,
        axes: s.axes,
        colors: styledScale(s),
        autoRange: s.colorbar.range === "auto",
        coastline: m.coastline,
        graticule: m.graticule,
        labels: m.labels,
        pointSize: m.pointSize,
        opacity: m.opacity,
        showNoData: m.showNoData,
        noData: s.colorbar.noData,
        colorbar: s.colorbar,
      },
    });
  };
  const download = async (file: { name: string; url: string }) => {
    setDownloading(true);
    setError("");
    try {
      const response = await fetchApi(file.url);
      const href = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = href;
      a.download = file.name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(href), 60000);
    } catch {
      setError("Download failed. Try again.");
    } finally {
      setDownloading(false);
    }
  };
  const files = task?.files?.files ?? [];
  const archive = files.find((f) => f.name.endsWith(".zip"));
  const images = files.filter((f) => f.name.endsWith(".png"));
  return (
    <details className="batch-render">
      <summary>Full-world batch render</summary>
      <p className="hint">
        Uses the appearance settings above. Full world: −180…180° longitude,
        −90…90° latitude. All times are UTC; both range endpoints are included
        when aligned with the step. Maximum 48 frames within three calendar
        dates.
      </p>
      {ranges.map((range, i) => (
        <fieldset key={i} className="render-range">
          <legend>Range {i + 1}</legend>
          {(["start", "end"] as const).map((key) => (
            <Field key={key} label={`${key === "start" ? "From" : "To"} (UTC)`}>
              <input
                type="datetime-local"
                step={30}
                value={range[key]}
                onChange={(e) =>
                  setRanges(
                    ranges.map((r, j) =>
                      j === i ? { ...r, [key]: e.target.value } : r,
                    ),
                  )
                }
              />
            </Field>
          ))}
          <button
            disabled={ranges.length === 1}
            onClick={() => setRanges(ranges.filter((_, j) => j !== i))}
          >
            Remove range
          </button>
        </fieldset>
      ))}
      <button
        disabled={ranges.length >= 48}
        onClick={() => setRanges([...ranges, { ...ranges[ranges.length - 1] }])}
      >
        Add range
      </button>
      <Field label="Time step">
        <select value={step} onChange={(e) => setStep(Number(e.target.value))}>
          {renderSteps.map((s) => (
            <option key={s} value={s}>
              {s < 60 ? `${s} seconds` : `${s / 60} minutes`}
            </option>
          ))}
        </select>
      </Field>
      <p aria-live="polite">
        {rangeError ||
          `${timestamps.length} unique frame(s) · overlapping ranges are merged`}
      </p>
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
      {assets.error && (
        <p role="alert">Render assets are unavailable. See the setup guide.</p>
      )}
      <button
        disabled={!assets.data || Boolean(busy) || Boolean(rangeError)}
        onClick={() => {
          try {
            const value = spec();
            setError("");
            void startRender(chart.id, value);
          } catch {
            setError("Check the render settings before submitting.");
          }
        }}
      >
        Render series
      </button>
      <button
        disabled={!assets.data || Boolean(rangeError)}
        onClick={() => {
          try {
            setPreview(spec());
            setError("");
          } catch {
            setError("Check the render settings.");
          }
        }}
      >
        Preview full-world frame
      </button>
      {error && <p role="alert">{error}</p>}
      {busy && (
        <button onClick={() => cancelRender(chart.id)}>Stop waiting</button>
      )}
      {preview && (
        <>
          <small>
            Preview uses the loaded frame and the same full-world renderer as
            the server. A later download may use newer source data.
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
          {archive && (
            <button
              disabled={downloading}
              onClick={() => void download(archive)}
            >
              Download ZIP ({images.length} maps)
            </button>
          )}
          {images.length === 1 && (
            <button
              disabled={downloading}
              onClick={() => void download(images[0])}
            >
              Download {images[0].name}
            </button>
          )}
          {images.length > 1 && (
            <details>
              <summary>Individual PNG files</summary>
              <ul>
                {images.map((f) => (
                  <li key={f.name}>
                    <button
                      disabled={downloading}
                      onClick={() => void download(f)}
                    >
                      {f.name}
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </details>
  );
}
