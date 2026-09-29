import { useQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
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
  const availability = useQuery({
    queryKey: ["availability", product.productId],
    queryFn: ({ signal }) => apiClient.availability(product.productId, signal),
  });
  const style = (patch: Partial<ChartSpec["styleSpec"]>) =>
    useWorkspace
      .getState()
      .update(chart.id, { styleSpec: { ...chart.styleSpec, ...patch } });
  const rangeInvalid =
    chart.styleSpec.vmin != null &&
    chart.styleSpec.vmax != null &&
    chart.styleSpec.vmin >= chart.styleSpec.vmax;
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
        <details className="availability">
          <summary>Data availability</summary>
          {availability.isPending ? (
            <p>Checking local index…</p>
          ) : availability.error ? (
            <p>
              Availability could not be checked. You can still request data.
            </p>
          ) : (
            <>
              <p>
                {availability.data.total} indexed entries ·{" "}
                {product.remoteAcquisition
                  ? "Backend can acquire remote data"
                  : "Local data required"}
              </p>
              {availability.data.timestamps.map((t) => (
                <code key={t}>{t}</code>
              ))}
              <small>{product.availabilityStrategy}</small>
            </>
          )}
        </details>
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
      <fieldset>
        <legend>Style</legend>
        <label className="field">
          Title
          <input
            value={chart.styleSpec.title}
            onChange={(e) => style({ title: e.target.value })}
          />
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={chart.styleSpec.legend}
            onChange={(e) => style({ legend: e.target.checked })}
          />{" "}
          Show legend
        </label>
        {product.capabilities.colorbar && (
          <>
            <label className="field">
              Palette
              <select
                value={chart.styleSpec.palette}
                onChange={(e) =>
                  style({
                    palette: e.target
                      .value as ChartSpec["styleSpec"]["palette"],
                  })
                }
              >
                <option value="viridis">Viridis</option>
                <option value="plasma">Plasma</option>
                <option value="ice">Ice</option>
              </select>
            </label>
            <div className="range-fields">
              {(["vmin", "vmax"] as const).map((key) => (
                <label className="field" key={key}>
                  {key}
                  <input
                    type="number"
                    step="any"
                    placeholder="Auto"
                    value={chart.styleSpec[key] ?? ""}
                    onChange={(e) =>
                      style({
                        [key]:
                          e.target.value === ""
                            ? undefined
                            : Number(e.target.value),
                      })
                    }
                  />
                </label>
              ))}
            </div>
            {rangeInvalid && (
              <p role="alert">vmax must exceed vmin. Using automatic bounds.</p>
            )}
          </>
        )}
      </fieldset>
    </div>
  );
}
