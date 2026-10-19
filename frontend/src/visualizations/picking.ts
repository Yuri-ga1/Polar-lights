/** Deck's index is relative to the layer's (sorted/filtered) data. */
export function pickedOriginalIndex(
  info: { index: number; object?: number | null },
  indexes: ArrayLike<number>,
): number | null {
  if (info.index < 0) return null;
  const original =
    typeof info.object === "number" ? info.object : indexes[info.index];
  return Number.isInteger(original) && original >= 0 ? original : null;
}
