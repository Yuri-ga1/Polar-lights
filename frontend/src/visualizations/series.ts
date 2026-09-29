import type { Result } from "../api/contracts";
export function sampleStatus(
  result: Extract<Result, { dataType: "timeseries" }>,
  column: string,
  index: number,
): string {
  if (result.columns[column][index] !== null) return "observed";
  const meta = result.metadata.columnMetadata?.[column];
  if (!result.metadata.nullPolicy || !meta?.frequencySeconds)
    return "null (unspecified)";
  const seconds = Date.parse(result.time[index]) / 1000;
  return (seconds - (meta.offsetSeconds ?? 0)) % meta.frequencySeconds === 0
    ? "missing_data"
    : "no_sample_expected";
}
export function seriesPoints(
  result: Extract<Result, { dataType: "timeseries" }>,
  column: string,
) {
  // Off-grid nulls are not gaps in this column. Expected-but-missing samples remain null.
  const indices = result.time
    .map((_, i) => i)
    .filter((i) => sampleStatus(result, column, i) !== "no_sample_expected");
  return {
    x: indices.map((i) => result.time[i]),
    y: indices.map((i) => result.columns[column][i]),
    customdata: indices.map((i) => sampleStatus(result, column, i)),
  };
}
