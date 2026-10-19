import { lazy, Suspense, useEffect, useState } from "react";
import { StyleEditor } from "./StyleEditor";
import { Timeline } from "./Timeline";
import { LayoutActions } from "./WorkspaceTools";
const BatchRender = lazy(() =>
  import("./BatchRender").then((m) => ({ default: m.BatchRender })),
);
import { validation, type Product, type Parameter } from "../api/contracts";
import { appliedChanged, useWorkspace, type ChartSpec } from "../store";
import { cancelRequest, requestChart } from "../requests";
import { isFutureUtcDate, latestUtcDateTime } from "../dateLimits";
function Field({
  parameter: p,
  chart,
  error,
}: {
  parameter: Parameter;
  chart: ChartSpec;
  error?: string;
}) {
  const value = chart.dataSpec[p.name];
  const [draft, setDraft] = useState(value == null ? "" : String(value));
  const [dateInputError, setDateInputError] = useState("");
  useEffect(() => {
    setDraft(value == null ? "" : String(value));
    setDateInputError("");
  }, [value]);
  const update = (value: string | number | string[]) =>
    useWorkspace
      .getState()
      .update(chart.id, { dataSpec: { ...chart.dataSpec, [p.name]: value } });
  const id = `param-${chart.id}-${p.name}`;
  const displayedError =
    p.type === "datetime" ? dateInputError || error : error;
  return (
    <label className="field" htmlFor={id}>
      <span>
        {p.name === "resolution"
          ? "Data sampling preset"
          : p.name === "samplingStride"
            ? "Custom data sampling stride"
            : p.name}
        {p.required && <b aria-label="required"> *</b>}
        {p.type === "datetime" && <small> UTC</small>}
      </span>
      {p.type === "datetime" ? (
        <input
          id={id}
          type="datetime-local"
          step="1"
          max={latestUtcDateTime()}
          required={p.required}
          aria-invalid={Boolean(displayedError)}
          aria-describedby={displayedError ? `${id}-error` : undefined}
          value={typeof value === "string" ? value.replace(/Z$/, "") : ""}
          onChange={(e) => {
            const entered = e.target.value;
            if (isFutureUtcDate(entered)) {
              setDateInputError("Date cannot be later than today (UTC).");
              return;
            }
            setDateInputError("");
            update(
              entered
                ? `${entered.length === 16 ? entered + ":00" : entered}Z`
                : "",
            );
          }}
        />
      ) : p.type === "integer" ? (
        <input
          id={id}
          type="text"
          inputMode="numeric"
          aria-label="Custom data sampling stride"
          aria-invalid={
            Boolean(error) ||
            (draft !== "" &&
              (!/^\d+$/.test(draft) ||
                Number(draft) < (p.minimum ?? 1) ||
                Number(draft) > (p.maximum ?? 1024)))
          }
          aria-describedby={error ? `${id}-error` : undefined}
          value={draft}
          placeholder="Preset"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            if (draft.trim() === "") {
              const next = { ...chart.dataSpec };
              delete next[p.name];
              useWorkspace.getState().update(chart.id, { dataSpec: next });
            } else update(/^\d+$/.test(draft) ? Number(draft) : draft);
          }}
        />
      ) : (
        <select
          id={id}
          required={p.required}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? `${id}-error` : undefined}
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
      {displayedError && (
        <small id={`${id}-error`} role="alert">
          {displayedError}
        </small>
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
            <Field
              key={p.name}
              parameter={p}
              chart={chart}
              error={errors.find((message) => message.startsWith(`${p.name} `))}
            />
          ))}
          {product.graphType === "map" &&
            product.productId !== "aurora-map" && (
              <p className="hint">
                Data sampling: custom stride overrides the preset; N selects
                every Nth stored sample (1–1024). This is not geographic grid
                spacing or export image resolution. The server applies a point
                limit (2,000,000 by default).
              </p>
            )}
        </fieldset>
        {product.productId !== "aurora-map" && (
          <Timeline key={chart.id} chart={chart} product={product} />
        )}
        {errors.some(
          (message) =>
            !product.parameterSchema.some((p) =>
              message.startsWith(`${p.name} `),
            ),
        ) && (
          <p className="hint" role="alert">
            {errors
              .filter(
                (message) =>
                  !product.parameterSchema.some((p) =>
                    message.startsWith(`${p.name} `),
                  ),
              )
              .join(" · ")}
          </p>
        )}
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
            Stop waiting
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
