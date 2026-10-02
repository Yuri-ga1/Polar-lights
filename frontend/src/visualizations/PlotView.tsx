import { useEffect, useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-cartesian-dist-min";
import type { Data, Layout } from "plotly.js";
import type { Result } from "../api/contracts";
import type { StyleSpec } from "../store";
import { seriesPoints } from "./series";
import { heatmapScale } from "./colors";
import { registerSvg } from "../exports";
import { KP_BAR_WIDTH_MS, kpColor, kpNotation } from "./kp";
export default function PlotView({
  result,
  style,
  chartId,
  productId,
}: {
  result: Exclude<Result, { dataType: "map" }>;
  style: StyleSpec;
  chartId: string;
  productId: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const data = useMemo<Data[]>(() => {
    if (result.dataType === "keogram") {
      const scale = heatmapScale(result.values.flat(), style);
      return [
        {
          type: "heatmap",
          x: result.time,
          y: result.latitude,
          z: result.values,
          colorscale: scale.scale,
          zmin: scale.low,
          zmax: scale.high,
          showscale: style.colorbar.visible,
          colorbar: {
            orientation:
              style.colorbar.orientation === "horizontal" ? "h" : "v",
            x: style.colorbar.x / 100,
            y: 1 - style.colorbar.y / 100,
            xanchor: "left",
            yanchor: "top",
            lenmode: "pixels",
            len: style.colorbar.length,
            thickness: style.colorbar.thickness,
            tickvals: style.colorbar.ticks.length
              ? style.colorbar.ticks
              : undefined,
            tickfont: {
              family: style.colorbar.font,
              size: style.colorbar.fontSize,
            },
            title: {
              text: `${style.colorbar.title} ${style.colorbar.units || (typeof result.metadata.units === "string" ? result.metadata.units : "")}`,
            },
          },
        },
      ];
    }
    if (productId === "kp") {
      const points = seriesPoints(result, "kp");
      const values = points.y.map((value) => value ?? 0);
      return [
        {
          type: "bar",
          x: points.x,
          y: values,
          width: points.x.map(() => KP_BAR_WIDTH_MS),
          marker: { color: values.map(kpColor) },
          text: values.map(kpNotation),
          textposition: "auto",
          name: "Kp",
          hovertemplate: "%{x}<br>Kp %{text}<br>%{customdata}<extra></extra>",
          customdata: points.customdata,
        } as Data,
      ];
    }
    return Object.keys(result.columns).map((column, i) => {
      const station = result.metadata.columnMetadata?.[column] as
        { latitude?: number; longitude?: number } | undefined;
      const locationText =
        station?.latitude != null && station.longitude != null
          ? `${station.latitude.toFixed(3)}°, ${station.longitude.toFixed(3)}°`
          : "";
      const location = locationText ? ` · ${locationText}` : "";
      const units =
        result.metadata.columnMetadata?.[column]?.units ||
        (typeof result.metadata.units === "object"
          ? result.metadata.units[column]
          : "") ||
        "";
      return {
        type: "scatter",
        mode: style.markers ? "lines+markers" : "lines",
        line: { width: style.lineWidth, dash: style.lineDash },
        marker: { size: style.markerSize, symbol: style.markerSymbol },
        ...seriesPoints(result, column),
        name: `${column}${location}${units ? ` (${units})` : ""}`,
        yaxis: i ? `y${i + 1}` : "y",
        connectgaps: false,
        hovertemplate: `%{x}<br>%{y} ${units}<br>%{customdata}${locationText ? `<br>Station position: ${locationText}` : ""}<extra>${column}</extra>`,
      } as Data;
    });
  }, [result, style, productId]);
  useEffect(() => {
    const node = host.current!;
    const layout: Partial<Layout> = {
      autosize: true,
      margin: style.margins,
      paper_bgcolor: style.background,
      plot_bgcolor:
        result.dataType === "keogram"
          ? style.colorbar.noData
          : style.background,
      font: { family: style.font, size: style.fontSize, color: "#42556a" },
      showlegend: style.legend,
      legend: { orientation: "h", y: -0.22 },
      xaxis: {
        title: { text: style.xLabel, font: { size: style.labelSize } },
        showgrid: style.grid,
        visible: style.axes,
        range: style.xMin && style.xMax ? [style.xMin, style.xMax] : undefined,
        autorange: !(style.xMin && style.xMax),
        type: "date",
        anchor: "free",
        position: 0,
      },
      uirevision: `${style.xMin}|${style.xMax}|${style.yMin}|${style.yMax}`,
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
            title: {
              text: style.yLabel || `${column} ${unit}`,
              font: { size: style.labelSize },
            },
            showgrid: style.grid,
            visible: style.axes,
            range:
              style.yMin != null && style.yMax != null
                ? [style.yMin, style.yMax]
                : undefined,
            autorange: !(style.yMin != null && style.yMax != null),
            domain: [
              1 - (i + 1) / count + (count > 1 ? 0.04 : 0),
              1 - i / count,
            ],
            automargin: true,
          },
        });
      });
      if (productId === "kp") {
        layout.yaxis = {
          title: { text: "Kp", font: { size: style.labelSize } },
          range: [0, 9],
          tickvals: [0, 3, 6, 9],
          showgrid: style.grid,
          visible: style.axes,
          fixedrange: false,
        };
        layout.shapes = style.stormLines
          .filter((line) => line.visible)
          .map((line) => ({
            type: "line",
            xref: "paper",
            x0: 0,
            x1: 1,
            yref: "y",
            y0: line.value,
            y1: line.value,
            line: { color: line.color, width: line.width, dash: line.dash },
            name: line.level,
          }));
        layout.annotations = style.stormLines
          .filter((line) => line.visible)
          .map((line) => ({
            xref: "paper",
            x: 1,
            y: line.value,
            text: line.level,
            showarrow: false,
            xanchor: "left",
            font: { color: line.color, size: style.labelSize },
          }));
      }
    } else
      layout.yaxis = {
        title: {
          text: style.yLabel || "Latitude (°)",
          font: { size: style.labelSize },
        },
        showgrid: style.grid,
        visible: style.axes,
        range:
          style.yMin != null && style.yMax != null
            ? [style.yMin, style.yMax]
            : undefined,
      };
    void Plotly.react(node, data, layout, {
      responsive: true,
      displaylogo: false,
      displayModeBar: style.modebar,
      scrollZoom: style.scrollZoom,
      modeBarButtonsToRemove: ["sendDataToCloud"],
    }).catch((e) => setError(String(e)));
  }, [data, result, style, productId]);
  useEffect(
    () =>
      registerSvg(chartId, () =>
        Plotly.toImage(host.current!, {
          format: "svg",
          width: host.current!.clientWidth,
          height: host.current!.clientHeight,
        }),
      ),
    [chartId],
  );
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
