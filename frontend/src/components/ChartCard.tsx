import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  memo,
  type ReactNode,
} from "react";
import { Rnd } from "react-rnd";
import { type Product, validation } from "../api/contracts";
import { chartState, useWorkspace, type ChartSpec } from "../store";
import { cancelRequest, removeChart, requestChart } from "../requests";
import { snapPosition } from "../workspace/geometry";
import { ChartExport } from "./WorkspaceTools";
const MapView = lazy(() => import("../visualizations/MapView"));
const PlotView = lazy(() => import("../visualizations/PlotView"));
class VisualBoundary extends Component<
  { children: ReactNode },
  { error: boolean }
> {
  state = { error: false };
  static getDerivedStateFromError() {
    return { error: true };
  }
  render() {
    return this.state.error ? (
      <p role="alert">
        Visualization could not be displayed. Try rebuilding this chart.
      </p>
    ) : (
      this.props.children
    );
  }
}
export const ChartCard = memo(function ChartCard({
  chart,
  product,
}: {
  chart: ChartSpec;
  product?: Product;
}) {
  const runtime = useWorkspace((s) => s.runtime[chart.id]);
  const selected = useWorkspace((s) => s.selectedIds.includes(chart.id));
  const mode = useWorkspace((s) => s.mode),
    snap = useWorkspace((s) => s.snap);
  const node = useRef<HTMLElement>(null);
  const [guides, setGuides] = useState<{ x?: number; y?: number }>({});
  const select = () => {
    if (!useWorkspace.getState().selectedIds.includes(chart.id))
      useWorkspace.getState().select(chart.id);
  };
  useEffect(() => {
    if (
      selected &&
      !document.activeElement?.closest("input,textarea,select,button")
    )
      node.current?.focus({ preventScroll: true });
  }, [selected]);
  useEffect(() => () => cancelRequest(chart.id), [chart.id]);
  const state = product ? chartState(chart, product, runtime) : "unconfigured";
  const result = runtime?.result;
  return (
    <Rnd
      size={{ width: chart.layoutSpec.width, height: chart.layoutSpec.height }}
      position={{ x: chart.layoutSpec.x, y: chart.layoutSpec.y }}
      minWidth={320}
      minHeight={260}
      bounds="parent"
      dragHandleClassName="card-drag-handle"
      cancel="button"
      style={{ zIndex: chart.layoutSpec.z }}
      disableDragging={chart.layoutSpec.locked}
      enableResizing={!chart.layoutSpec.locked && mode === "free"}
      dragGrid={snap ? [20, 20] : undefined}
      resizeGrid={snap ? [20, 20] : undefined}
      onDragStart={select}
      onResizeStart={select}
      onDrag={(_, d) => {
        if (mode === "grid") return;
        const s = useWorkspace.getState();
        setGuides(
          snapPosition(
            { ...chart.layoutSpec, x: d.x, y: d.y },
            s.charts
              .filter((c) => !s.selectedIds.includes(c.id))
              .map((c) => c.layoutSpec),
            snap,
          ).guides,
        );
      }}
      onDragStop={(_, d) => {
        const s = useWorkspace.getState();
        const next =
          mode === "free"
            ? snapPosition(
                { ...chart.layoutSpec, x: d.x, y: d.y },
                s.charts
                  .filter((c) => !s.selectedIds.includes(c.id))
                  .map((c) => c.layoutSpec),
                snap,
              )
            : d;
        s.move(chart.id, next.x, next.y);
        setGuides({});
      }}
      onResizeStop={(_, __, ref, ___, position) =>
        useWorkspace.getState().resize(chart.id, {
          ...position,
          width: ref.offsetWidth,
          height: ref.offsetHeight,
        })
      }
      resizeHandleClasses={{ bottomRight: "resize-corner" }}
    >
      <article
        ref={node}
        className={`chart-card ${selected ? "selected" : ""}`}
        data-testid="chart-card"
        data-chart-id={chart.id}
        data-state={state}
        data-selected={selected}
        data-locked={chart.layoutSpec.locked}
        data-group={chart.layoutSpec.groupId ?? ""}
        style={{
          background: chart.styleSpec.background,
          fontFamily: chart.styleSpec.font,
          fontSize: chart.styleSpec.fontSize,
        }}
        onPointerDown={(e) => {
          if (e.shiftKey) {
            e.preventDefault();
            useWorkspace.getState().select(chart.id, true);
          } else select();
        }}
        onFocus={(e) => {
          if (e.target === e.currentTarget) select();
        }}
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          if (e.key === " " || e.key === "Enter") {
            e.preventDefault();
            useWorkspace.getState().select(chart.id, e.shiftKey);
          }
          if (e.key.startsWith("Arrow") && !chart.layoutSpec.locked) {
            e.preventDefault();
            const d = e.shiftKey ? 20 : 1;
            useWorkspace
              .getState()
              .move(
                chart.id,
                chart.layoutSpec.x +
                  (e.key === "ArrowRight" ? d : e.key === "ArrowLeft" ? -d : 0),
                chart.layoutSpec.y +
                  (e.key === "ArrowDown" ? d : e.key === "ArrowUp" ? -d : 0),
              );
          }
        }}
        tabIndex={0}
        aria-label={`${chart.styleSpec.title} chart`}
      >
        <header className="card-drag-handle">
          <span className="grip" aria-hidden="true" data-export-ignore>
            ⠿
          </span>
          <h3>{chart.styleSpec.title || product?.title || chart.productId}</h3>
          <span className="card-type" data-export-ignore>
            {chart.layoutSpec.locked
              ? "Locked"
              : chart.layoutSpec.groupId
                ? "Grouped"
                : product?.graphType}
          </span>
          <button
            aria-label="Duplicate chart"
            title="Duplicate"
            onClick={() => useWorkspace.getState().duplicate(chart.id)}
          >
            ⧉
          </button>
          <button
            aria-label="Delete chart"
            disabled={chart.layoutSpec.locked}
            title="Delete"
            onClick={() => removeChart(chart.id)}
          >
            ×
          </button>
        </header>
        {chart.styleSpec.subtitle && (
          <div className="chart-subtitle">{chart.styleSpec.subtitle}</div>
        )}
        <div className="chart-body">
          {!product ? (
            <div className="placeholder">
              This product is no longer in the catalog.
            </div>
          ) : !result && state !== "loading" && state !== "error" ? (
            <div className="placeholder">
              <span className="placeholder-icon">
                {product.graphType === "map" ? "◎" : "⌁"}
              </span>
              <strong>
                {state === "unconfigured"
                  ? "Choose parameters"
                  : "Ready to build"}
              </strong>
              <p>
                {validation(product, chart.dataSpec).join(" · ") ||
                  "Press Build chart in the inspector."}
              </p>
            </div>
          ) : null}
          {result && (
            <VisualBoundary
              key={`${chart.id}-${JSON.stringify(chart.appliedDataSpec)}`}
            >
              <Suspense
                fallback={
                  <div className="placeholder">Loading visualization…</div>
                }
              >
                {result.dataType === "map" ? (
                  <MapView
                    result={result}
                    style={chart.styleSpec}
                    chartId={chart.id}
                    projectionAllowed={Boolean(
                      product?.capabilities.projection,
                    )}
                  />
                ) : (
                  <PlotView
                    result={result}
                    style={chart.styleSpec}
                    chartId={chart.id}
                    productId={chart.productId}
                  />
                )}
              </Suspense>
            </VisualBoundary>
          )}
          {state === "loading" && (
            <div className="status-overlay" role="status">
              <span className="spinner" /> {runtime?.progress || "Loading"}
              <button onClick={() => cancelRequest(chart.id)}>Cancel</button>
            </div>
          )}
          {state === "error" && (
            <div className="error-overlay" role="alert">
              <strong>Request failed</strong>
              <code>{runtime?.errorCode}</code>
              <p>{runtime?.error}</p>
              {runtime?.requestId && (
                <small>Request ID: {runtime.requestId}</small>
              )}
              <button
                onClick={() => product && void requestChart(chart.id, product)}
              >
                Retry
              </button>
            </div>
          )}
        </div>
        <footer>
          {result ? (
            <>
              <span>{result.metadata.timestamp || "UTC"}</span>
              <span>
                {result.metadata.resolution}
                {result.dataType === "map" &&
                  ` · ${result.metadata.pointCount ?? result.lat.length} points`}
              </span>
              <span>
                {typeof result.metadata.units === "string"
                  ? result.metadata.units
                  : ""}
              </span>
              <details data-export-ignore>
                <summary>Metadata</summary>
                <pre>
                  {JSON.stringify(
                    Object.fromEntries(
                      Object.entries(result.metadata).filter(([key]) =>
                        [
                          "timestamp",
                          "units",
                          "resolution",
                          "pointCount",
                          "missingData",
                          "datasetVersion",
                          "source",
                          "generatedAt",
                          "partial",
                          "columnMetadata",
                          "nullPolicy",
                          "missingTimestamps",
                        ].includes(key),
                      ),
                    ),
                    null,
                    2,
                  )}
                </pre>
              </details>
            </>
          ) : (
            <span>{state.replaceAll("_", " ")}</span>
          )}
        </footer>
        <ChartExport
          chart={chart}
          isPlot={product?.graphType !== "map"}
          loaded={Boolean(result)}
        />
      </article>
      {guides.x !== undefined && (
        <div
          data-export-ignore
          className="snap-guide vertical"
          style={{ left: guides.x - chart.layoutSpec.x }}
        />
      )}
      {guides.y !== undefined && (
        <div
          data-export-ignore
          className="snap-guide horizontal"
          style={{ top: guides.y - chart.layoutSpec.y }}
        />
      )}
    </Rnd>
  );
});
