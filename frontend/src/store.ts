import { hashKey } from "@tanstack/react-query";
import { create } from "zustand";
import {
  defaults,
  validation,
  type Product,
  type Result,
  type DataSpec,
} from "./api/contracts";
import {
  defaultStyle,
  emptyWorkspace,
  parsePreset,
  serializePreset,
  type ChartSpec,
  type WorkspaceSpec,
  type Rect,
} from "./workspace/schema";
import { boundsOf, expandedIds, units } from "./workspace/geometry";
export type { ChartSpec, StyleSpec } from "./workspace/schema";
export type { DataSpec };
export type Runtime = {
  status: "loading" | "loaded" | "error";
  result?: Result;
  error?: string;
  errorCode?: string;
  requestId?: string;
  progress?: string;
};
export const STORAGE_KEY = "polar-lights.workspace.v1";
function productPresentation(chart: ChartSpec): ChartSpec {
  const maximum =
    chart.productId === "roti-map"
      ? 1
      : chart.productId === "tec-adjusted-map" || chart.productId === "gim-map"
        ? 60
        : undefined;
  const style = chart.styleSpec;
  if (
    maximum !== undefined &&
    style.colorbar.range === "auto" &&
    style.vmin === undefined &&
    style.vmax === undefined
  )
    return {
      ...chart,
      styleSpec: {
        ...style,
        vmin: 0,
        vmax: maximum,
        colorbar: { ...style.colorbar, range: "recommended" },
      },
    };
  if (chart.productId === "kp" && !style.stormLines.length)
    return {
      ...chart,
      styleSpec: {
        ...style,
        stormLines: defaultStyle("", "kp").stormLines,
      },
    };
  return chart;
}
function normalizePresentation(workspace: WorkspaceSpec): WorkspaceSpec {
  return {
    ...workspace,
    charts: workspace.charts.map(productPresentation),
  };
}
function restore() {
  try {
    return normalizePresentation(
      parsePreset(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null")),
    );
  } catch {
    return emptyWorkspace();
  }
}
type Patch = Partial<
  Pick<ChartSpec, "dataSpec" | "styleSpec" | "layoutSpec" | "appliedDataSpec">
>;
type Workspace = WorkspaceSpec & {
  selectedId: string | null;
  runtime: Record<string, Runtime>;
  persistenceError: string | null;
  past: WorkspaceSpec[];
  future: WorkspaceSpec[];
  clipboard: ChartSpec[];
  epoch: number;
  select: (id: string | null, additive?: boolean) => void;
  selectMany: (ids: string[], additive?: boolean) => void;
  add: (product: Product, position?: { x: number; y: number }) => string;
  update: (id: string, patch: Patch) => void;
  remove: (id: string) => void;
  removeSelected: () => void;
  duplicate: (id?: string) => void;
  copy: () => void;
  paste: () => void;
  move: (id: string, x: number, y: number) => void;
  resize: (id: string, rect: Rect) => void;
  align: (
    direction: "left" | "center" | "right" | "top" | "middle" | "bottom",
  ) => void;
  distribute: (axis: "x" | "y") => void;
  group: () => void;
  ungroup: () => void;
  order: (front: boolean) => void;
  lock: (locked: boolean) => void;
  setMode: (mode: "free" | "grid") => void;
  setOptions: (
    patch: Partial<Pick<WorkspaceSpec, "snap" | "gridColumns">>,
  ) => void;
  undo: () => void;
  redo: () => void;
  importPreset: (input: unknown) => void;
  setRuntime: (id: string, state?: Runtime) => void;
};
export function snapshot(s: WorkspaceSpec): WorkspaceSpec {
  return {
    charts: s.charts,
    selectedIds: s.selectedIds,
    mode: s.mode,
    snap: s.snap,
    gridColumns: s.gridColumns,
  };
}
function grid(charts: ChartSpec[], columns: number) {
  return charts.map((c, i) => ({
    ...c,
    layoutSpec: {
      ...c.layoutSpec,
      x: 24 + (i % columns) * 580,
      y: 24 + Math.floor(i / columns) * 400,
      width: 560,
      height: 380,
    },
  }));
}
export const useWorkspace = create<Workspace>((set, get) => {
  const commit = (patch: Partial<WorkspaceSpec>) => {
    const s = get(),
      next = { ...snapshot(s), ...patch };
    if (hashKey([next]) === hashKey([snapshot(s)])) return;
    set({
      ...next,
      selectedId: next.selectedIds.at(-1) ?? null,
      past: [...s.past, snapshot(s)].slice(-80),
      future: [],
    });
  };
  const selection = (ids: string[], additive = false) => {
    const s = get(),
      expanded = expandedIds(s.charts, ids),
      selectedIds = additive
        ? [...new Set([...s.selectedIds, ...expanded])]
        : expanded;
    set({ selectedIds, selectedId: selectedIds.at(-1) ?? null });
  };
  const shiftUnits = (deltas: Map<string, { x: number; y: number }>) => {
    const s = get();
    commit({
      charts: s.charts.map((c) => {
        const d = deltas.get(c.id);
        return d
          ? {
              ...c,
              layoutSpec: {
                ...c.layoutSpec,
                x: Math.max(0, c.layoutSpec.x + d.x),
                y: Math.max(0, c.layoutSpec.y + d.y),
              },
            }
          : c;
      }),
    });
  };
  return {
    ...restore(),
    selectedId: null,
    runtime: {},
    persistenceError: null,
    past: [],
    future: [],
    clipboard: [],
    epoch: 0,
    select: (id, additive = false) => {
      if (!id) {
        selection([]);
        return;
      }
      const s = get();
      if (additive && s.selectedIds.includes(id)) {
        const remove = expandedIds(s.charts, [id]);
        selection(s.selectedIds.filter((i) => !remove.includes(i)));
      } else selection([id], additive);
    },
    selectMany: selection,
    add: (product, position) => {
      const s = get(),
        id = crypto.randomUUID(),
        offset = s.charts.length * 28;
      let charts: ChartSpec[] = [
        ...s.charts,
        {
          id,
          productId: product.productId,
          dataSpec: defaults(product),
          styleSpec: defaultStyle(product.title, product.productId),
          layoutSpec: {
            x: position?.x ?? 32 + offset,
            y: position?.y ?? 32 + offset,
            width: 560,
            height: 380,
            z: Math.max(0, ...s.charts.map((c) => c.layoutSpec.z)) + 1,
            locked: false,
          },
        },
      ];
      if (s.mode === "grid") charts = grid(charts, s.gridColumns);
      commit({ charts, selectedIds: [id] });
      return id;
    },
    update: (id, patch) => {
      const s = get(),
        charts = s.charts.map((c) => (c.id === id ? { ...c, ...patch } : c));
      if (Object.keys(patch).every((k) => k === "appliedDataSpec"))
        set({ charts });
      else commit({ charts });
    },
    remove: (id) => {
      const s = get(),
        ids = expandedIds(s.charts, [id]);
      if (s.charts.some((c) => ids.includes(c.id) && c.layoutSpec.locked))
        return;
      commit({
        charts: s.charts.filter((c) => !ids.includes(c.id)),
        selectedIds: s.selectedIds.filter((i) => !ids.includes(i)),
      });
    },
    removeSelected: () => {
      const s = get(),
        ids = units(s.charts, s.selectedIds).flatMap((g) =>
          g.cards.map((c) => c.id),
        );
      commit({
        charts: s.charts.filter((c) => !ids.includes(c.id)),
        selectedIds: s.selectedIds.filter((i) => !ids.includes(i)),
      });
    },
    copy: () => {
      const s = get();
      set({
        clipboard: structuredClone(
          s.charts.filter((c) => s.selectedIds.includes(c.id)),
        ),
      });
    },
    paste: () => {
      const s = get(),
        groups = new Map<string, string>();
      const copies = s.clipboard.map((original, i) => {
        const c = structuredClone(original);
        c.id = crypto.randomUUID();
        if (c.layoutSpec.groupId) {
          if (!groups.has(c.layoutSpec.groupId))
            groups.set(c.layoutSpec.groupId, crypto.randomUUID());
          c.layoutSpec.groupId = groups.get(c.layoutSpec.groupId);
        }
        c.layoutSpec = {
          ...c.layoutSpec,
          x: c.layoutSpec.x + 32,
          y: c.layoutSpec.y + 32,
          z: Math.max(0, ...s.charts.map((c) => c.layoutSpec.z)) + i + 1,
          locked: false,
        };
        return c;
      });
      if (!copies.length) return;
      const charts = [...s.charts, ...copies];
      commit({
        charts: s.mode === "grid" ? grid(charts, s.gridColumns) : charts,
        selectedIds: copies.map((c) => c.id),
      });
    },
    duplicate: (id) => {
      const s = get(),
        ids = id ? expandedIds(s.charts, [id]) : s.selectedIds,
        old = s.clipboard;
      set({
        clipboard: structuredClone(s.charts.filter((c) => ids.includes(c.id))),
      });
      get().paste();
      set({ clipboard: old });
    },
    move: (id, x, y) => {
      const s = get(),
        c = s.charts.find((c) => c.id === id);
      if (!c) return;
      const ids = s.selectedIds.includes(id)
          ? expandedIds(s.charts, s.selectedIds)
          : expandedIds(s.charts, [id]),
        movable = units(s.charts, ids).flatMap((g) => g.cards);
      if (!movable.some((c) => c.id === id)) return;
      if (s.mode === "grid") {
        const index = Math.min(
            s.charts.length - 1,
            Math.max(
              0,
              Math.floor(y / 400) * s.gridColumns + Math.floor(x / 580),
            ),
          ),
          rest = s.charts.filter((c) => !movable.includes(c));
        rest.splice(index, 0, ...movable);
        commit({ charts: grid(rest, s.gridColumns) });
        return;
      }
      const box = boundsOf(movable.map((c) => c.layoutSpec)),
        dx = Math.max(x - c.layoutSpec.x, -box.x),
        dy = Math.max(y - c.layoutSpec.y, -box.y);
      shiftUnits(new Map(movable.map((c) => [c.id, { x: dx, y: dy }])));
    },
    resize: (id, rect) => {
      const s = get(),
        c = s.charts.find((c) => c.id === id);
      if (!c || s.mode === "grid") return;
      const group = units(s.charts, [id])[0];
      if (!group) return;
      if (group.cards.length > 1) {
        const anchor = c.layoutSpec,
          sx = rect.width / c.layoutSpec.width,
          sy = rect.height / c.layoutSpec.height;
        if (
          group.cards.some(
            (c) =>
              c.layoutSpec.width * sx < 320 ||
              c.layoutSpec.height * sy < 260 ||
              c.layoutSpec.width * sx > 4000 ||
              c.layoutSpec.height * sy > 4000 ||
              rect.x + (c.layoutSpec.x - anchor.x) * sx < 0 ||
              rect.y + (c.layoutSpec.y - anchor.y) * sy < 0,
          )
        )
          return;
        commit({
          charts: s.charts.map((c) =>
            group.cards.includes(c)
              ? {
                  ...c,
                  layoutSpec: {
                    ...c.layoutSpec,
                    x: rect.x + (c.layoutSpec.x - anchor.x) * sx,
                    y: rect.y + (c.layoutSpec.y - anchor.y) * sy,
                    width: c.layoutSpec.width * sx,
                    height: c.layoutSpec.height * sy,
                  },
                }
              : c,
          ),
        });
      } else get().update(id, { layoutSpec: { ...c.layoutSpec, ...rect } });
    },
    align: (direction) => {
      const s = get(),
        items = units(s.charts, s.selectedIds);
      if (items.length < 2 || s.mode === "grid") return;
      const box = boundsOf(items.map((i) => i.bounds)),
        deltas = new Map<string, { x: number; y: number }>();
      for (const i of items) {
        let x = 0,
          y = 0;
        const r = i.bounds;
        if (direction === "left") x = box.x - r.x;
        if (direction === "right") x = box.x + box.width - r.x - r.width;
        if (direction === "center")
          x = box.x + box.width / 2 - r.x - r.width / 2;
        if (direction === "top") y = box.y - r.y;
        if (direction === "bottom") y = box.y + box.height - r.y - r.height;
        if (direction === "middle")
          y = box.y + box.height / 2 - r.y - r.height / 2;
        for (const c of i.cards) deltas.set(c.id, { x, y });
      }
      shiftUnits(deltas);
    },
    distribute: (axis) => {
      const s = get(),
        items = units(s.charts, s.selectedIds).sort(
          (a, b) => a.bounds[axis] - b.bounds[axis],
        );
      if (items.length < 3 || s.mode === "grid") return;
      const size = axis === "x" ? "width" : "height",
        first = items[0].bounds,
        last = items.at(-1)!.bounds,
        gap =
          (last[axis] +
            last[size] -
            first[axis] -
            items.reduce((n, i) => n + i.bounds[size], 0)) /
          (items.length - 1);
      let cursor = first[axis];
      const deltas = new Map<string, { x: number; y: number }>();
      for (const i of items) {
        for (const c of i.cards)
          deltas.set(c.id, {
            x: axis === "x" ? cursor - i.bounds.x : 0,
            y: axis === "y" ? cursor - i.bounds.y : 0,
          });
        cursor += i.bounds[size] + gap;
      }
      shiftUnits(deltas);
    },
    group: () => {
      const s = get();
      if (
        s.selectedIds.length < 2 ||
        s.charts.some(
          (c) => s.selectedIds.includes(c.id) && c.layoutSpec.locked,
        )
      )
        return;
      const groupId = crypto.randomUUID();
      commit({
        charts: s.charts.map((c) =>
          s.selectedIds.includes(c.id)
            ? { ...c, layoutSpec: { ...c.layoutSpec, groupId } }
            : c,
        ),
      });
    },
    ungroup: () => {
      const s = get();
      commit({
        charts: s.charts.map((c) =>
          s.selectedIds.includes(c.id) && !c.layoutSpec.locked
            ? { ...c, layoutSpec: { ...c.layoutSpec, groupId: undefined } }
            : c,
        ),
      });
    },
    order: (front) => {
      const s = get(),
        ids = units(s.charts, s.selectedIds).flatMap((i) =>
          i.cards.map((c) => c.id),
        ),
        sorted = [...s.charts].sort((a, b) => a.layoutSpec.z - b.layoutSpec.z),
        chosen = sorted.filter((c) => ids.includes(c.id)),
        other = sorted.filter((c) => !ids.includes(c.id)),
        ordered = front ? [...other, ...chosen] : [...chosen, ...other];
      commit({
        charts: s.charts.map((c) => ({
          ...c,
          layoutSpec: { ...c.layoutSpec, z: ordered.indexOf(c) },
        })),
      });
    },
    lock: (locked) => {
      const s = get();
      commit({
        charts: s.charts.map((c) =>
          s.selectedIds.includes(c.id)
            ? { ...c, layoutSpec: { ...c.layoutSpec, locked } }
            : c,
        ),
      });
    },
    setMode: (mode) => {
      const s = get();
      if (mode === s.mode) return;
      const charts =
        mode === "grid"
          ? grid(
              s.charts.map((c) => ({
                ...c,
                layoutSpec: {
                  ...c.layoutSpec,
                  free: {
                    x: c.layoutSpec.x,
                    y: c.layoutSpec.y,
                    width: c.layoutSpec.width,
                    height: c.layoutSpec.height,
                  },
                },
              })),
              s.gridColumns,
            )
          : s.charts.map((c) => ({
              ...c,
              layoutSpec: { ...c.layoutSpec, ...c.layoutSpec.free },
            }));
      commit({ charts, mode });
    },
    setOptions: (patch) => {
      const s = get();
      commit({
        ...patch,
        ...(patch.gridColumns && s.mode === "grid"
          ? { charts: grid(s.charts, patch.gridColumns) }
          : {}),
      });
    },
    undo: () => {
      const s = get(),
        prev = s.past.at(-1);
      if (!prev) return;
      set({
        ...prev,
        selectedId: prev.selectedIds.at(-1) ?? null,
        past: s.past.slice(0, -1),
        future: [snapshot(s), ...s.future].slice(0, 80),
        epoch: s.epoch + 1,
      });
    },
    redo: () => {
      const s = get(),
        next = s.future[0];
      if (!next) return;
      set({
        ...next,
        selectedId: next.selectedIds.at(-1) ?? null,
        past: [...s.past, snapshot(s)].slice(-80),
        future: s.future.slice(1),
        epoch: s.epoch + 1,
      });
    },
    importPreset: (input) => {
      const next = normalizePresentation(parsePreset(input));
      commit(next);
      set({ runtime: {}, epoch: get().epoch + 1 });
    },
    setRuntime: (id, state) =>
      set((s) => {
        if (!s.charts.some((c) => c.id === id)) return s;
        const runtime = { ...s.runtime };
        if (state) runtime[id] = state;
        else delete runtime[id];
        return { runtime };
      }),
  };
});
useWorkspace.setState((s) => ({ selectedId: s.selectedIds.at(-1) ?? null }));
useWorkspace.subscribe((s, prev) => {
  if (
    s.charts === prev.charts &&
    s.selectedIds === prev.selectedIds &&
    s.mode === prev.mode &&
    s.snap === prev.snap &&
    s.gridColumns === prev.gridColumns
  )
    return;
  try {
    localStorage.setItem(STORAGE_KEY, serializePreset(snapshot(s)));
    if (s.persistenceError) useWorkspace.setState({ persistenceError: null });
  } catch {
    if (!s.persistenceError)
      useWorkspace.setState({
        persistenceError:
          "Workspace could not be saved. Browser storage may be full or unavailable.",
      });
  }
});
export function chartState(
  chart: ChartSpec,
  product: Product,
  runtime?: Runtime,
) {
  return (
    runtime?.status ??
    (validation(product, chart.dataSpec).length
      ? "unconfigured"
      : "ready_to_request")
  );
}
export function appliedChanged(chart: ChartSpec) {
  return (
    chart.appliedDataSpec &&
    hashKey([chart.appliedDataSpec]) !== hashKey([chart.dataSpec])
  );
}
