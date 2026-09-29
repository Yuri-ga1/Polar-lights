import { Component, lazy, Suspense, useEffect, type ReactNode } from "react";
import { Rnd } from "react-rnd";
import { type Product, validation } from "../api/contracts";
import { chartState, useWorkspace, type ChartSpec } from "../store";
import { cancelRequest, removeChart, requestChart } from "../requests";
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
export function ChartCard({
  chart,
  product,
}: {
  chart: ChartSpec;
  product?: Product;
}) {
  const runtime = useWorkspace((s) => s.runtime[chart.id]);
  const selected = useWorkspace((s) => s.selectedId === chart.id);
  const select = () => useWorkspace.getState().select(chart.id);
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
      style={{ zIndex: selected ? 2 : 1 }}
      onDragStart={select}
      onResizeStart={select}
      onDragStop={(_, d) =>
        useWorkspace.getState().update(chart.id, {
          layoutSpec: { ...chart.layoutSpec, x: d.x, y: d.y },
        })
      }
      onResizeStop={(_, __, ref, ___, position) =>
        useWorkspace.getState().update(chart.id, {
          layoutSpec: {
            ...position,
            width: ref.offsetWidth,
            height: ref.offsetHeight,
          },
        })
      }
      resizeHandleClasses={{ bottomRight: "resize-corner" }}
    >
      <article
        className={`chart-card ${selected ? "selected" : ""}`}
        data-testid="chart-card"
        data-chart-id={chart.id}
        data-state={state}
        onPointerDown={select}
        onFocus={select}
        tabIndex={0}
        aria-label={`${chart.styleSpec.title} chart`}
      >
        <header className="card-drag-handle">
          <span className="grip" aria-hidden="true">
            ⠿
          </span>
          <h3>{chart.styleSpec.title || product?.title || chart.productId}</h3>
          <span className="card-type">{product?.graphType}</span>
          <button
            aria-label="Duplicate chart"
            title="Duplicate"
            onClick={() => useWorkspace.getState().duplicate(chart.id)}
          >
            ⧉
          </button>
          <button
            aria-label="Delete chart"
            title="Delete"
            onClick={() => removeChart(chart.id)}
          >
            ×
          </button>
        </header>
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
                  <MapView result={result} style={chart.styleSpec} />
                ) : (
                  <PlotView result={result} style={chart.styleSpec} />
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
              <p>{runtime?.error}</p>
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
              <details>
                <summary>Metadata</summary>
                <pre>{JSON.stringify(result.metadata, null, 2)}</pre>
              </details>
            </>
          ) : (
            <span>{state.replaceAll("_", " ")}</span>
          )}
        </footer>
      </article>
    </Rnd>
  );
}
