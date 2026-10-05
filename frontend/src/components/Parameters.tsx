import { lazy, Suspense } from "react";
import { StyleEditor } from "./StyleEditor";
import { Timeline } from "./Timeline";
import { LayoutActions } from "./WorkspaceTools";
const BatchRender = lazy(() =>
  import("./BatchRender").then((m) => ({ default: m.BatchRender })),
);
import { validation, type Product, type Parameter } from "../api/contracts";
import { appliedChanged, useWorkspace, type ChartSpec } from "../store";
import { cancelRequest, requestChart } from "../requests";
function Field({
  parameter: p,
  chart,
}: {
  parameter: Parameter;
  chart: ChartSpec;
}) {
  const value = chart.dataSpec[p.name];
  const update = (value: string | number | string[]) =>
    useWorkspace
      .getState()
      .update(chart.id, { dataSpec: { ...chart.dataSpec, [p.name]: value } });
  const id = `param-${chart.id}-${p.name}`;
  return (
    <label className="field" htmlFor={id}>
      <span>
        {p.name}
        {p.required && <b aria-label="required"> *</b>}
        {p.type === "datetime" && <small> UTC</small>}
      </span>
      {p.type === "datetime" ? (
        <input
          id={id}
          type="datetime-local"
          step="1"
          required={p.required}
          value={typeof value === "string" ? value.replace(/Z$/, "") : ""}
          onChange={(e) =>
            update(
              e.target.value
                ? `${e.target.value.length === 16 ? e.target.value + ":00" : e.target.value}Z`
                : "",
            )
          }
        />
      ) : (
        <select
          id={id}
          required={p.required}
          multiple={p.type === "multiselect"}
          value={value ?? (p.type === "multiselect" ? [] : "")}
          onChange={(e) => {
            if (p.type === "multiselect")
              update(Array.from(e.target.selectedOptions, (o) => o.value));
            else
              update(
                p.values?.find((v) => String(v) === e.target.value) ??
                  e.target.value,
              );
          }}
        >
          {p.type === "select" && <option value="">Select…</option>}
          {p.values?.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      )}
    </label>
  );
}
export function Parameters({
  chart,
  product,
}: {
  chart: ChartSpec;
  product: Product;
}) {
  const runtime = useWorkspace((s) => s.runtime[chart.id]);
  const errors = validation(product, chart.dataSpec);
  return (
    <div className="parameters" key={chart.id}>
      <div className="panel-heading">
        <span className="eyebrow">INSPECTOR</span>
        <h2>{product.title}</h2>
        <p>Parameters for the selected chart</p>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void requestChart(chart.id, product);
        }}
      >
        <fieldset>
          <legend>Data</legend>
          {product.parameterSchema.map((p) => (
            <Field key={p.name} parameter={p} chart={chart} />
          ))}
        </fieldset>
        {product.productId !== "aurora-map" && (
          <Timeline key={chart.id} chart={chart} product={product} />
        )}
        {errors.length > 0 && <p className="hint">{errors.join(" · ")}</p>}
        {appliedChanged(chart) && (
          <p className="hint">
            Draft changed. The chart shows the last successful request.
          </p>
        )}
        <button
          className="primary"
          type="submit"
          disabled={errors.length > 0 || !product.available}
        >
          {runtime?.status === "loading" ? "Restart request" : "Build chart"}
        </button>
        {runtime?.status === "loading" && (
          <button type="button" onClick={() => cancelRequest(chart.id)}>
            Cancel request
          </button>
        )}
      </form>
      <LayoutActions chart={chart} />
      <StyleEditor key={chart.id} chart={chart} product={product} />
      {product.capabilities.renderJobs && (
        <Suspense fallback={<p>Loading render controls…</p>}>
          <BatchRender key={chart.id} chart={chart} />
        </Suspense>
      )}
    </div>
  );
}
