import { snapshot, useWorkspace, type ChartSpec } from "./store";
import { serializePreset } from "./workspace/schema";
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function exportPreset(chart?: ChartSpec) {
  const s = snapshot(useWorkspace.getState());
  saveBlob(
    new Blob(
      [
        serializePreset(
          chart ? { ...s, charts: [chart], selectedIds: [chart.id] } : s,
        ),
      ],
      { type: "application/json" },
    ),
    chart ? "chart-preset.json" : "workspace.json",
  );
}
const exporters = new Map<string, () => Promise<string>>();
const mapPreparers = new Map<string, () => Promise<void>>();
export function registerMapExport(id: string, prepare: () => Promise<void>) {
  mapPreparers.set(id, prepare);
  return () => {
    if (mapPreparers.get(id) === prepare) mapPreparers.delete(id);
  };
}
export function waitForMapIdle(map: {
  once: (event: "idle", callback: () => void) => unknown;
  off: (event: "idle", callback: () => void) => unknown;
  triggerRepaint: () => void;
}): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      map.off("idle", finished);
      reject(
        new Error(
          "Map did not finish rendering before export. Try again after it loads.",
        ),
      );
    }, 15000);
    const finished = () => {
      window.clearTimeout(timer);
      resolve();
    };
    map.once("idle", finished);
    map.triggerRepaint();
  });
}
/** Freeze each WebGL layer explicitly as an image before html-to-image clones
 * the DOM. Its normal canvas clone may read an empty drawing buffer. */
export function freezeMapCanvases(node: HTMLElement): () => void {
  const restore: Array<() => void> = [];
  try {
    for (const canvas of node.querySelectorAll<HTMLCanvasElement>(
      ".map-host canvas, .map-canvas canvas",
    )) {
      const context = canvas.getContext("webgl2") || canvas.getContext("webgl");
      if (!canvas.width || !canvas.height || context?.isContextLost())
        throw new Error(
          "Map graphics context is unavailable. Reload the map and try again.",
        );
      let data: string;
      try {
        data = canvas.toDataURL("image/png");
      } catch {
        throw new Error(
          "Could not capture the map graphics. Reload the map and try again.",
        );
      }
      if (data === "data:," || data.length < 100)
        throw new Error(
          "Map graphics are empty. Wait for the map to render and try again.",
        );
      const parent = canvas.parentElement;
      if (!parent) continue;
      const canvasBox = canvas.getBoundingClientRect();
      const parentBox = parent.getBoundingClientRect();
      const image = document.createElement("img");
      image.src = data;
      image.alt = "";
      image.setAttribute("data-export-layer", "");
      Object.assign(image.style, {
        position: "absolute",
        left: `${canvasBox.left - parentBox.left}px`,
        top: `${canvasBox.top - parentBox.top}px`,
        width: `${canvasBox.width}px`,
        height: `${canvasBox.height}px`,
        pointerEvents: "none",
      });
      const oldPosition = parent.style.position;
      const oldVisibility = canvas.style.visibility;
      if (getComputedStyle(parent).position === "static")
        parent.style.position = "relative";
      canvas.style.visibility = "hidden";
      canvas.after(image);
      restore.push(() => {
        image.removeAttribute("src");
        image.remove();
        canvas.style.visibility = oldVisibility;
        parent.style.position = oldPosition;
      });
    }
    return () => restore.reverse().forEach((cleanup) => cleanup());
  } catch (error) {
    restore.reverse().forEach((cleanup) => cleanup());
    throw error;
  }
}
export function registerSvg(id: string, exporter: () => Promise<string>) {
  exporters.set(id, exporter);
  return () => {
    exporters.delete(id);
  };
}
export async function exportVisual(format: "png" | "pdf" | "svg", id?: string) {
  const node = id
    ? document.querySelector<HTMLElement>(`[data-chart-id="${CSS.escape(id)}"]`)
    : document.getElementById("workspace-canvas");
  if (!node) throw new Error("Nothing to export");
  if (format === "svg") {
    if (!id || !exporters.has(id))
      throw new Error("SVG is available only for loaded Plotly charts.");
    const image = await exporters.get(id)!();
    const inner = new DOMParser().parseFromString(
      decodeURIComponent(image.slice(image.indexOf(",") + 1)),
      "image/svg+xml",
    ).documentElement;
    const chart = useWorkspace.getState().charts.find((c) => c.id === id)!;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    svg.setAttribute("width", String(node.offsetWidth));
    svg.setAttribute("height", String(node.offsetHeight));
    const bg = document.createElementNS(svg.namespaceURI, "rect");
    bg.setAttribute("width", "100%");
    bg.setAttribute("height", "100%");
    bg.setAttribute("fill", chart.styleSpec.background);
    svg.append(bg);
    [chart.styleSpec.title, chart.styleSpec.subtitle]
      .filter(Boolean)
      .forEach((label, i) => {
        const text = document.createElementNS(svg.namespaceURI, "text");
        text.setAttribute("x", "12");
        text.setAttribute("y", String(25 + i * 22));
        text.setAttribute("font-family", chart.styleSpec.font);
        text.setAttribute("font-size", String(chart.styleSpec.fontSize));
        text.textContent = label;
        svg.append(text);
      });
    const body = node.querySelector<HTMLElement>(".plot-host")!;
    inner.setAttribute(
      "x",
      String(
        body.getBoundingClientRect().left - node.getBoundingClientRect().left,
      ),
    );
    inner.setAttribute(
      "y",
      String(
        body.getBoundingClientRect().top - node.getBoundingClientRect().top,
      ),
    );
    svg.append(inner);
    saveBlob(
      new Blob([new XMLSerializer().serializeToString(svg)], {
        type: "image/svg+xml",
      }),
      "chart.svg",
    );
    return;
  }
  const width = node.offsetWidth,
    height = node.offsetHeight;
  if (width * height > 32_000_000)
    throw new Error(
      "This canvas exceeds the 32 megapixel export limit. Export individual cards or reduce the workspace size.",
    );
  const { toPng } = await import("html-to-image");
  document.documentElement.classList.add("exporting");
  let restoreCanvases: (() => void) | undefined;
  try {
    await document.fonts.ready;
    const chartIds = id
      ? [id]
      : [...node.querySelectorAll<HTMLElement>("[data-chart-id]")].map(
          (card) => card.dataset.chartId!,
        );
    await Promise.all(chartIds.map((chartId) => mapPreparers.get(chartId)?.()));
    restoreCanvases = freezeMapCanvases(node);
    const data = await toPng(node, {
      width,
      height,
      pixelRatio: 1,
      backgroundColor: "#ffffff",
      ...(id
        ? {
            style: {
              position: "relative",
              left: "0",
              top: "0",
              transform: "none",
            },
          }
        : {}),
      filter: (n) =>
        !(
          n instanceof HTMLElement &&
          (n.hasAttribute("data-export-ignore") ||
            n.tagName === "BUTTON" ||
            n.classList.contains("maplibregl-ctrl-attrib") ||
            n.classList.contains("map-hud"))
        ),
    });
    if (format === "png")
      saveBlob(
        await (await fetch(data)).blob(),
        id ? "chart.png" : "workspace.png",
      );
    else {
      const { jsPDF } = await import("jspdf");
      const pdf = new jsPDF({
        orientation: width > height ? "landscape" : "portrait",
        unit: "px",
        format: [width, height],
        hotfixes: ["px_scaling"],
      });
      pdf.addImage(data, "PNG", 0, 0, width, height);
      pdf.save(id ? "chart.pdf" : "workspace.pdf");
    }
  } finally {
    restoreCanvases?.();
    document.documentElement.classList.remove("exporting");
  }
}
