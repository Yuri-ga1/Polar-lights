// Backend uses 0.115 days; this is the same 2.76-hour width in exact ms.
export const KP_BAR_WIDTH_MS = 9_936_000;

export function kpColor(value: number): string {
  if (value < 3.5) return "#2e9d4d";
  if (value <= 4.5) return "#e5bd25";
  return "#d44545";
}

/** Scientific Kp notation: whole, plus one third, or minus one third. */
export function kpNotation(value: number): string {
  const thirds = Math.round(value * 3);
  // GFZ values in processed/kp.csv are intentionally stored to three decimal
  // places (for example 8.333 and 8.667), not as exact binary thirds.
  if (Math.abs(value - thirds / 3) > 0.002) return String(value);
  const remainder = ((thirds % 3) + 3) % 3;
  if (remainder === 0) return `${thirds / 3}o`;
  if (remainder === 1) return `${Math.floor(thirds / 3)}+`;
  return `${Math.ceil(thirds / 3)}−`;
}
