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
  try {
    await document.fonts.ready;
    const data = await toPng(node, {
      width,
      height,
      pixelRatio: 1,
      backgroundColor: "#ffffff",
      filter: (n) =>
        !(
          n instanceof HTMLElement &&
          (n.hasAttribute("data-export-ignore") ||
            n.tagName === "BUTTON" ||
            n.classList.contains("maplibregl-control-container") ||
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
    document.documentElement.classList.remove("exporting");
  }
}
