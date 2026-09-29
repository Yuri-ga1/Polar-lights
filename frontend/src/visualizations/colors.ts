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
  const min = style.vmin ?? low,
    max = style.vmax ?? high;
  return max > min ? [min, max] : [low, high > low ? high : low + 1];
}
export function colorScale(palette: StyleSpec["palette"]): [number, string][] {
  return palettes[palette].map((c, i, a) => [
    i / (a.length - 1),
    `rgb(${c.join(",")})`,
  ]);
}
