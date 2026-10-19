import { useRef, useState } from "react";
import { validateExportSize, type ExportSize } from "../exportSizing";
import { exportVisual } from "../exports";

let lastSize: ExportSize | undefined;
export function ExportOptions({
  chartId,
  disabled = false,
  svg = false,
}: {
  chartId?: string;
  disabled?: boolean;
  svg?: boolean;
}) {
  const node = chartId
    ? document.querySelector<HTMLElement>(
        `[data-chart-id="${CSS.escape(chartId)}"]`,
      )
    : document.getElementById("workspace-canvas");
  const [width, setWidth] = useState(
    String(lastSize?.width ?? Math.max(256, node?.offsetWidth || 1200)),
  );
  const [height, setHeight] = useState(
    String(lastSize?.height ?? Math.max(256, node?.offsetHeight || 700)),
  );
  const [dpi, setDpi] = useState<ExportSize["dpi"]>(lastSize?.dpi ?? 150);
  const [locked, setLocked] = useState(true);
  const ratio = useRef((Number(width) || 1200) / (Number(height) || 700));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const size = { width: Number(width), height: Number(height), dpi };
  const sizeError = validateExportSize(size);
  const setDimension = (axis: "width" | "height", raw: string) => {
    if (axis === "width") {
      setWidth(raw);
      if (locked && Number(raw) > 0)
        setHeight(String(Math.round(Number(raw) / ratio.current)));
    } else {
      setHeight(raw);
      if (locked && Number(raw) > 0)
        setWidth(String(Math.round(Number(raw) * ratio.current)));
    }
  };
  const save = async (format: "png" | "pdf" | "svg") => {
    setBusy(true);
    setError("");
    try {
      if (format !== "svg") {
        if (sizeError) throw Error(sizeError);
        lastSize = size;
      }
      await exportVisual(format, chartId, format === "svg" ? undefined : size);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Export failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="export-options">
      <p className="hint">
        Current {chartId ? "chart" : "workspace"} snapshot · PNG/PDF. Pixel size
        controls the saved render, not scientific data or card layout. Map
        points use the live map canvas; enlarge the card before export for
        sharper points. PDF page size is pixels ÷ DPI.
      </p>
      <div className="export-size-fields">
        <label>
          Width (px)
          <input
            type="text"
            inputMode="numeric"
            aria-invalid={Boolean(sizeError)}
            value={width}
            onChange={(e) => setDimension("width", e.target.value)}
          />
        </label>
        <label>
          Height (px)
          <input
            type="text"
            inputMode="numeric"
            aria-invalid={Boolean(sizeError)}
            value={height}
            onChange={(e) => setDimension("height", e.target.value)}
          />
        </label>
        <label>
          Print DPI
          <select
            value={dpi}
            onChange={(e) =>
              setDpi(Number(e.target.value) as ExportSize["dpi"])
            }
          >
            {[150, 300, 600].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={locked}
          onChange={(e) => {
            if (e.target.checked)
              ratio.current = (Number(width) || 1200) / (Number(height) || 700);
            setLocked(e.target.checked);
          }}
        />
        Lock aspect ratio
      </label>
      <div className="export-presets">
        {(
          [
            ["Landscape", 2400, 1600],
            ["Portrait", 1600, 2400],
            ["Square", 2000, 2000],
          ] as const
        ).map(([label, w, h]) => (
          <button
            key={label}
            type="button"
            onClick={() => {
              ratio.current = w / h;
              setWidth(String(w));
              setHeight(String(h));
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <small>
        {Number.isFinite(size.width * size.height)
          ? ((size.width * size.height) / 1_000_000).toFixed(1)
          : "—"}{" "}
        MP · {width} × {height} px · {dpi} DPI
      </small>
      {sizeError && <p role="alert">{sizeError}</p>}
      {(["png", "pdf"] as const).map((format) => (
        <button
          key={format}
          type="button"
          disabled={disabled || busy || Boolean(sizeError)}
          onClick={() => void save(format)}
        >
          Save {format.toUpperCase()}
        </button>
      ))}
      {svg && (
        <button
          type="button"
          disabled={disabled || busy}
          onClick={() => void save("svg")}
        >
          Save SVG (Plotly)
        </button>
      )}
      {!svg && chartId && (
        <small>Vector SVG is available for Plotly charts only.</small>
      )}
      {busy && <p role="status">Preparing export…</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
