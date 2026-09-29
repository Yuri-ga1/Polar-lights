import type { ChartSpec, Rect } from "./schema";
export function boundsOf(rects: Rect[]): Rect {
  const x = Math.min(...rects.map((r) => r.x)),
    y = Math.min(...rects.map((r) => r.y));
  return {
    x,
    y,
    width: Math.max(...rects.map((r) => r.x + r.width)) - x,
    height: Math.max(...rects.map((r) => r.y + r.height)) - y,
  };
}
export function intersects(a: Rect, b: Rect) {
  return (
    a.x <= b.x + b.width &&
    a.x + a.width >= b.x &&
    a.y <= b.y + b.height &&
    a.y + a.height >= b.y
  );
}
export function expandedIds(charts: ChartSpec[], ids: string[]) {
  const groups = new Set(
    charts
      .filter((c) => ids.includes(c.id))
      .map((c) => c.layoutSpec.groupId)
      .filter(Boolean),
  );
  return charts
    .filter(
      (c) =>
        ids.includes(c.id) ||
        Boolean(c.layoutSpec.groupId && groups.has(c.layoutSpec.groupId)),
    )
    .map((c) => c.id);
}
export function units(charts: ChartSpec[], ids: string[]) {
  const groups = new Map<string, ChartSpec[]>();
  const selected = expandedIds(charts, ids);
  for (const c of charts.filter((c) => selected.includes(c.id))) {
    const key = c.layoutSpec.groupId ?? c.id;
    groups.set(key, [...(groups.get(key) ?? []), c]);
  }
  return [...groups.values()]
    .filter((g) => !g.some((c) => c.layoutSpec.locked))
    .map((cards) => ({
      cards,
      bounds: boundsOf(cards.map((c) => c.layoutSpec)),
    }));
}
export function snapPosition(rect: Rect, others: Rect[], snap: boolean) {
  let x = snap ? Math.round(rect.x / 20) * 20 : rect.x,
    y = snap ? Math.round(rect.y / 20) * 20 : rect.y;
  const guides: { x?: number; y?: number } = {};
  let dx = 7,
    dy = 7;
  for (const r of others) {
    for (const a of [0, rect.width / 2, rect.width])
      for (const b of [r.x, r.x + r.width / 2, r.x + r.width])
        if (Math.abs(b - rect.x - a) < dx) {
          dx = Math.abs(b - rect.x - a);
          x = b - a;
          guides.x = b;
        }
    for (const a of [0, rect.height / 2, rect.height])
      for (const b of [r.y, r.y + r.height / 2, r.y + r.height])
        if (Math.abs(b - rect.y - a) < dy) {
          dy = Math.abs(b - rect.y - a);
          y = b - a;
          guides.y = b;
        }
  }
  return { x: Math.max(0, x), y: Math.max(0, y), guides };
}
