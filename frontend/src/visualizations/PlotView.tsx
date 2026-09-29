import { useEffect, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-cartesian-dist-min";
import type { Data, Layout } from "plotly.js";
import type { Result } from "../api/contracts";
import type { StyleSpec } from "../store";
import { seriesPoints } from "./series";
import { bounds, colorScale } from "./colors";
export default function PlotView({
  result,
  style,
}: {
  result: Exclude<Result, { dataType: "map" }>;
  style: StyleSpec;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const data = useMemo<Data[]>(() => {
    if (result.dataType === "keogram") {
      const range = bounds(
        (function* () {
          for (const row of result.values) yield* row;
        })(),
        style,
      );
      return [
        {
          type: "heatmap",
          x: result.time,
          y: result.latitude,
          z: result.values,
          colorscale: colorScale(style.palette),
          zmin: range[0],
          zmax: range[1],
          showscale: style.legend,
          colorbar: {
            title: {
              text:
                typeof result.metadata.units === "string"
                  ? result.metadata.units
                  : "",
            },
          },
        },
      ];
    }
    return Object.keys(result.columns).map((column, i) => {
      const units =
        result.metadata.columnMetadata?.[column]?.units ||
        (typeof result.metadata.units === "object"
          ? result.metadata.units[column]
          : "") ||
        "";
      return {
        type: "scatter",
        mode: "lines",
        ...seriesPoints(result, column),
        name: `${column}${units ? ` (${units})` : ""}`,
        yaxis: i ? `y${i + 1}` : "y",
        connectgaps: false,
        hovertemplate: `%{x}<br>%{y} ${units}<br>%{customdata}<extra>${column}</extra>`,
      } as Data;
    });
  }, [result, style.palette, style.vmin, style.vmax, style.legend]);
  useEffect(() => {
    const node = host.current!;
    const layout: Partial<Layout> = {
      autosize: true,
      margin: { l: 65, r: 28, t: 15, b: 48 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      font: { family: "system-ui", size: 11, color: "#42556a" },
      showlegend: style.legend,
      legend: { orientation: "h", y: -0.22 },
      xaxis: {
        title: { text: "Time (UTC)" },
        type: "date",
        anchor: "free",
        position: 0,
      },
      uirevision: "retain-view",
    };
    if (result.dataType === "timeseries") {
      const columns = Object.keys(result.columns),
        count = columns.length;
      columns.forEach((column, i) => {
        const unit =
          result.metadata.columnMetadata?.[column]?.units ??
          (typeof result.metadata.units === "object"
            ? result.metadata.units[column]
            : "") ??
          "";
        Object.assign(layout, {
          [i ? `yaxis${i + 1}` : "yaxis"]: {
            title: { text: `${column} ${unit}` },
            domain: [
              1 - (i + 1) / count + (count > 1 ? 0.04 : 0),
              1 - i / count,
            ],
            automargin: true,
          },
        });
      });
    } else layout.yaxis = { title: { text: "Latitude (°)" } };
    void Plotly.react(node, data, layout, {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["sendDataToCloud"],
    }).catch((e) => setError(String(e)));
  }, [data, result, style.legend]);
  useEffect(() => {
    const node = host.current!;
    const observer = new ResizeObserver(() => {
      void Promise.resolve(Plotly.Plots.resize(node)).catch(() => {});
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
      Plotly.purge(node);
    };
  }, []);
  return (
    <div className="plot-view" data-testid="plot-view">
      <div ref={host} className="plot-host" />
      {result.metadata.partial && (
        <span className="partial-label">Partial data · gaps are preserved</span>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
