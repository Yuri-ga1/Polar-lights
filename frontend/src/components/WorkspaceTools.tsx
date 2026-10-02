import { useEffect, useRef, useState } from "react";
import { useWorkspace, type ChartSpec } from "../store";
import { exportPreset, exportVisual } from "../exports";
import { Numeric } from "./Controls";
export function LayoutActions({ chart }: { chart?: ChartSpec }) {
  const selected = useWorkspace((s) => s.selectedIds);
  const mode = useWorkspace((s) => s.mode);
  const action = useWorkspace.getState();
  return (
    <fieldset className="layout-actions">
      <legend>
        Layout {selected.length > 1 ? `· ${selected.length} selected` : ""}
      </legend>
      {chart && (
        <div className="geometry-fields">
          {(["x", "y", "width", "height"] as const).map((key) => (
            <Numeric
              key={key}
              label={key}
              value={chart.layoutSpec[key]}
              min={key === "width" ? 320 : key === "height" ? 260 : 0}
              max={key === "width" || key === "height" ? 4000 : 20000}
              onChange={(v) => {
                if (
                  v === undefined ||
                  chart.layoutSpec.locked ||
                  mode === "grid"
                )
                  return;
                if (key === "x" || key === "y")
                  action.move(
                    chart.id,
                    key === "x" ? v : chart.layoutSpec.x,
                    key === "y" ? v : chart.layoutSpec.y,
                  );
                else action.resize(chart.id, { ...chart.layoutSpec, [key]: v });
              }}
            />
          ))}
        </div>
      )}
      <div className="action-grid">
        {(["left", "center", "right", "top", "middle", "bottom"] as const).map(
          (direction) => (
            <button
              key={direction}
              disabled={selected.length < 2 || mode === "grid"}
              onClick={() => action.align(direction)}
            >
              Align {direction}
            </button>
          ),
        )}
        <button
          disabled={selected.length < 3 || mode === "grid"}
          onClick={() => action.distribute("x")}
        >
          Distribute horizontally
        </button>
        <button
          disabled={selected.length < 3 || mode === "grid"}
          onClick={() => action.distribute("y")}
        >
          Distribute vertically
        </button>
        <button disabled={selected.length < 2} onClick={action.group}>
          Group
        </button>
        <button disabled={!selected.length} onClick={action.ungroup}>
          Ungroup
        </button>
        <button disabled={!selected.length} onClick={() => action.order(true)}>
          Bring to front
        </button>
        <button disabled={!selected.length} onClick={() => action.order(false)}>
          Send to back
        </button>
        <button disabled={!selected.length} onClick={() => action.lock(true)}>
          Lock
        </button>
        <button disabled={!selected.length} onClick={() => action.lock(false)}>
          Unlock
        </button>
        <button disabled={!selected.length} onClick={action.copy}>
          Copy
        </button>
        <button disabled={!selected.length} onClick={() => action.duplicate()}>
          Duplicate selection
        </button>
        <button disabled={!selected.length} onClick={action.removeSelected}>
          Delete selection
        </button>
        <button onClick={() => action.select(null)}>Clear selection</button>
      </div>
    </fieldset>
  );
}
function isEditing(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    Boolean(target.closest('input,textarea,select,[contenteditable="true"]'))
  );
}
export function useShortcuts() {
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (isEditing(event.target)) return;
      const s = useWorkspace.getState(),
        key = event.key.toLowerCase(),
        mod = event.ctrlKey || event.metaKey;
      let action: (() => void) | undefined;
      if (key === "escape") action = () => s.select(null);
      if (key === "delete" || key === "backspace") action = s.removeSelected;
      if (mod) {
        if (key === "c") action = s.copy;
        if (key === "v") action = s.paste;
        if (key === "d") action = () => s.duplicate();
        if (key === "z") action = event.shiftKey ? s.redo : s.undo;
        if (key === "s") action = () => exportPreset();
        if (key === "a") action = () => s.selectMany(s.charts.map((c) => c.id));
      }
      if (action) {
        event.preventDefault();
        action();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
}
export function WorkspaceTools() {
  const s = useWorkspace();
  const file = useRef<HTMLInputElement>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const exportImage = async (format: "png" | "pdf") => {
    setBusy(true);
    setError("");
    try {
      await exportVisual(format);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Export failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <div
        className="workspace-tools"
        role="toolbar"
        aria-label="Workspace tools"
      >
        <button disabled={!s.past.length} onClick={s.undo} title="Ctrl/Cmd+Z">
          Undo
        </button>
        <button
          disabled={!s.future.length}
          onClick={s.redo}
          title="Ctrl/Cmd+Shift+Z"
        >
          Redo
        </button>
        <label>
          Layout mode
          <select
            aria-label="Layout mode"
            value={s.mode}
            onChange={(e) => s.setMode(e.target.value as "free" | "grid")}
          >
            <option value="free">Free canvas</option>
            <option value="grid">Grid layout</option>
          </select>
        </label>
        {s.mode === "grid" ? (
          <label>
            Columns
            <select
              aria-label="Grid columns"
              value={s.gridColumns}
              onChange={(e) =>
                s.setOptions({ gridColumns: Number(e.target.value) })
              }
            >
              {[1, 2, 3, 4, 5, 6].map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </label>
        ) : (
          <label className="check">
            <input
              type="checkbox"
              checked={s.snap}
              onChange={(e) => s.setOptions({ snap: e.target.checked })}
            />
            Snap to grid
          </label>
        )}
        <button onClick={() => s.selectMany(s.charts.map((c) => c.id))}>
          Select all
        </button>
        <button disabled={!s.clipboard.length} onClick={s.paste}>
          Paste
        </button>
        <button onClick={() => exportPreset()}>Export preset</button>
        <button onClick={() => file.current?.click()}>Import preset</button>
        <button
          disabled={busy || !s.charts.length}
          onClick={() => void exportImage("png")}
        >
          Workspace PNG
        </button>
        <button
          disabled={busy || !s.charts.length}
          onClick={() => void exportImage("pdf")}
        >
          Workspace PDF
        </button>
        <input
          ref={file}
          hidden
          type="file"
          accept="application/json,.json"
          aria-label="Import workspace file"
          onChange={async (e) => {
            const selected = e.target.files?.[0];
            if (!selected) return;
            try {
              if (selected.size > 2_000_000)
                throw new Error("Preset exceeds 2 MB");
              s.importPreset(JSON.parse(await selected.text()));
              setError("");
            } catch (err) {
              setError(err instanceof Error ? err.message : "Invalid preset");
            }
            e.target.value = "";
          }}
        />
      </div>
      {busy && <p role="status">Preparing export…</p>}
      {error && <p role="alert">{error}</p>}
    </>
  );
}
export function ChartExport({
  chart,
  isPlot,
  loaded,
}: {
  chart: ChartSpec;
  isPlot: boolean;
  loaded: boolean;
}) {
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <details data-export-ignore className="chart-export">
      <summary>Export chart</summary>
      {(["png", "pdf", ...(isPlot ? (["svg"] as const) : [])] as const).map(
        (format) => (
          <button
            key={format}
            disabled={!loaded || busy}
            onClick={async () => {
              setBusy(true);
              try {
                await exportVisual(format, chart.id);
                setError("");
              } catch (e) {
                setError(e instanceof Error ? e.message : "Export failed");
              } finally {
                setBusy(false);
              }
            }}
          >
            {format.toUpperCase()}
          </button>
        ),
      )}
      <button onClick={() => exportPreset(chart)}>JSON preset</button>
      {!isPlot && <small>WebGL maps export as PNG or PDF.</small>}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
