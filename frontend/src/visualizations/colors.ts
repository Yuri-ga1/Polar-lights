import type { StyleSpec } from "../store";
const palettes = {
  viridis: [
    [68, 1, 84],
    [59, 82, 139],
    [33, 145, 140],
    [94, 201, 98],
    [253, 231, 37],
  ],
  plasma: [
    [13, 8, 135],
    [126, 3, 168],
    [204, 71, 120],
    [248, 149, 64],
    [240, 249, 33],
  ],
  ice: [
    [12, 34, 65],
    [18, 81, 112],
    [39, 138, 156],
    [114, 204, 194],
    [227, 251, 227],
  ],
};
export function color(
  value: number,
  min: number,
  max: number,
  palette: StyleSpec["palette"],
): [number, number, number, number] {
  const colors = palettes[palette];
  const t =
    Math.max(0, Math.min(1, (value - min) / (max - min || 1))) *
    (colors.length - 1);
  const a = colors[Math.floor(t)],
    b = colors[Math.min(colors.length - 1, Math.floor(t) + 1)];
  return [0, 1, 2]
    .map((i) => Math.round(a[i] + (b[i] - a[i]) * (t % 1)))
    .concat(220) as [number, number, number, number];
}
export function bounds(
  values: Iterable<number | null>,
  style: StyleSpec,
): [number, number] {
  let low = Infinity,
    high = -Infinity;
  for (const value of values)
    if (value != null && Number.isFinite(value)) {
      low = Math.min(low, value);
      high = Math.max(high, value);
    }
  if (!Number.isFinite(low)) {
    low = 0;
    high = 1;
  }
  const fixedRange =
    style.colorbar.range === "manual" || style.colorbar.range === "recommended";
  const min = fixedRange ? (style.vmin ?? low) : low,
    max = fixedRange ? (style.vmax ?? high) : high;
  return max > min ? [min, max] : [low, high > low ? high : low + 1];
}
export function drawOrder(
  values: readonly (number | null)[],
  showNoData: boolean,
): number[] {
  return values
    .map((_, index) => index)
    .filter((index) => showNoData || values[index] != null)
    .sort((a, b) => (values[a] ?? -Infinity) - (values[b] ?? -Infinity));
}
export function colorScale(palette: StyleSpec["palette"]): [number, string][] {
  return palettes[palette].map((c, i, a) => [
    i / (a.length - 1),
    `rgb(${c.join(",")})`,
  ]);
}
export function rgb(hex: string): [number, number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
    255,
  ];
}
export function styledColor(
  value: number | null,
  min: number,
  max: number,
  style: StyleSpec,
): [number, number, number, number] {
  const c = style.colorbar;
  if (value === null || !Number.isFinite(value)) return rgb(c.noData);
  if (value < min) return rgb(c.under);
  if (value > max) return rgb(c.over);
  let t = Math.max(0, Math.min(1, (value - min) / (max - min || 1)));
  if (c.mode === "discrete")
    t = Math.min(c.levels - 1, Math.floor(t * c.levels)) / (c.levels - 1);
  if (c.reverse) t = 1 - t;
  if (c.stops.length < 2)
    return color(t, 0, 1, style.palette).map((v, i) => (i === 3 ? 255 : v)) as [
      number,
      number,
      number,
      number,
    ];
  const stops = [...c.stops].sort((a, b) => a.at - b.at),
    a = [...stops].reverse().find((s) => s.at <= t) ?? stops[0],
    b = stops.find((s) => s.at >= t) ?? stops.at(-1)!;
  const ca = rgb(a.color),
    cb = rgb(b.color),
    fraction = (t - a.at) / (b.at - a.at || 1);
  return ca.map((v, i) =>
    i === 3
      ? 255
      : Math.round(v + (cb[i] - v) * Math.max(0, Math.min(1, fraction))),
  ) as [number, number, number, number];
}
export function styledScale(style: StyleSpec): [number, string][] {
  if (style.colorbar.mode === "discrete") {
    return Array.from({ length: style.colorbar.levels }, (_, i) => {
      const c = `rgb(${styledColor(i / (style.colorbar.levels - 1), 0, 1, style)
        .slice(0, 3)
        .join(",")})`;
      return [
        [i / style.colorbar.levels, c],
        [(i + 1) / style.colorbar.levels, c],
      ] as [number, string][];
    }).flat();
  }
  return Array.from({ length: 65 }, (_, i) => [
    i / 64,
    `rgb(${styledColor(i / 64, 0, 1, style)
      .slice(0, 3)
      .join(",")})`,
  ]);
}
// Extend only the display scale, never the dataset, to represent under/over colors.
export function heatmapScale(
  values: Iterable<number | null>,
  style: StyleSpec,
) {
  const range = bounds(values, style),
    actual = bounds(values, {
      ...style,
      colorbar: { ...style.colorbar, range: "auto" },
    });
  const low = Math.min(actual[0], range[0]),
    high = Math.max(actual[1], range[1]),
    span = high - low;
  const start = (range[0] - low) / span,
    end = (range[1] - low) / span;
  const scale: [number, string][] = styledScale(style).map(([t, c]) => [
    start + t * (end - start),
    c,
  ]);
  if (start > 0)
    scale.unshift([0, style.colorbar.under], [start, style.colorbar.under]);
  if (end < 1) scale.push([end, style.colorbar.over], [1, style.colorbar.over]);
  return { scale, low, high, range };
}
