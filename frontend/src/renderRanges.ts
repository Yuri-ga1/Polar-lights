export type RenderRange = { start: string; end: string };
export const renderSteps = [30, 60, 120, 300, 600, 900, 1800, 3600] as const;
export function rangeTimestamps(
  ranges: RenderRange[],
  seconds: number,
): string[] {
  if (!renderSteps.some((step) => step === seconds))
    throw Error("Choose a time step.");
  const times = new Set<number>();
  for (const range of ranges) {
    const start = Date.parse(`${range.start}Z`),
      end = Date.parse(`${range.end}Z`);
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start)
      throw Error("Enter a valid UTC start and end for each range.");
    if (start % 30000 || end % 30000)
      throw Error("Times must align with the 30-second data cadence.");
    if ((end - start) / (seconds * 1000) >= 48)
      throw Error("Maximum 48 frames. Choose a larger step or shorter ranges.");
    for (let t = start; t <= end; t += seconds * 1000) {
      times.add(t);
      if (times.size > 48)
        throw Error(
          "Maximum 48 frames. Choose a larger step or shorter ranges.",
        );
    }
  }
  const ordered = [...times].sort((a, b) => a - b);
  if (!ordered.length) throw Error("Add at least one range.");
  if (
    Math.floor(ordered.at(-1)! / 86400000) - Math.floor(ordered[0] / 86400000) >
    2
  )
    throw Error("Ranges must fit within three consecutive UTC calendar dates.");
  return ordered.map((t) => new Date(t).toISOString());
}
