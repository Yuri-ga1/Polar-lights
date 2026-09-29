import { hashKey } from "@tanstack/react-query";
import { create } from "zustand";
import { z } from "zod";
import {
  defaults,
  validation,
  type DataSpec,
  type Product,
  type Result,
} from "./api/contracts";
const dataSchema = z.record(
  z.union([z.string(), z.number(), z.array(z.string())]),
);
const styleSchema = z.object({
  title: z.string(),
  legend: z.boolean(),
  palette: z.enum(["viridis", "plasma", "ice"]),
  vmin: z.number().optional(),
  vmax: z.number().optional(),
});
const layoutSchema = z.object({
  x: z.number().min(0),
  y: z.number().min(0),
  width: z.number().min(320),
  height: z.number().min(260),
});
const chartSchema = z.object({
  id: z.string(),
  productId: z.string(),
  dataSpec: dataSchema,
  appliedDataSpec: dataSchema.optional(),
  styleSpec: styleSchema,
  layoutSpec: layoutSchema,
});
export type ChartSpec = z.infer<typeof chartSchema>;
export type StyleSpec = ChartSpec["styleSpec"];
export type Runtime = {
  status: "loading" | "loaded" | "error";
  result?: Result;
  error?: string;
  progress?: string;
};
export const STORAGE_KEY = "polar-lights.workspace.v1";
const workspaceSchema = z.object({
  version: z.literal(1),
  charts: z.array(chartSchema),
  selectedId: z.string().nullable(),
});
function restore() {
  try {
    return workspaceSchema.parse(
      JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"),
    );
  } catch {
    return { version: 1 as const, charts: [] as ChartSpec[], selectedId: null };
  }
}
type Workspace = {
  charts: ChartSpec[];
  selectedId: string | null;
  runtime: Record<string, Runtime>;
  persistenceError: string | null;
  select: (id: string | null) => void;
  add: (product: Product, position?: { x: number; y: number }) => string;
  update: (
    id: string,
    patch: Partial<
      Pick<
        ChartSpec,
        "dataSpec" | "styleSpec" | "layoutSpec" | "appliedDataSpec"
      >
    >,
  ) => void;
  remove: (id: string) => void;
  duplicate: (id: string) => void;
  setRuntime: (id: string, state?: Runtime) => void;
};
export const useWorkspace = create<Workspace>((set, get) => ({
  ...restore(),
  runtime: {},
  persistenceError: null,
  select: (selectedId) => set({ selectedId }),
  add: (product, position) => {
    const id = crypto.randomUUID();
    const offset = get().charts.length * 28;
    set((s) => ({
      charts: [
        ...s.charts,
        {
          id,
          productId: product.productId,
          dataSpec: defaults(product),
          styleSpec: { title: product.title, legend: true, palette: "viridis" },
          layoutSpec: {
            x: position?.x ?? 32 + offset,
            y: position?.y ?? 32 + offset,
            width: 560,
            height: 380,
          },
        },
      ],
      selectedId: id,
    }));
    return id;
  },
  update: (id, patch) =>
    set((s) => ({
      charts: s.charts.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    })),
  remove: (id) =>
    set((s) => {
      const runtime = { ...s.runtime };
      delete runtime[id];
      return {
        charts: s.charts.filter((c) => c.id !== id),
        runtime,
        selectedId: s.selectedId === id ? null : s.selectedId,
      };
    }),
  duplicate: (id) => {
    const original = get().charts.find((c) => c.id === id);
    if (!original) return;
    const copy = structuredClone(original);
    copy.id = crypto.randomUUID();
    copy.layoutSpec.x += 32;
    copy.layoutSpec.y += 32;
    set((s) => ({ charts: [...s.charts, copy], selectedId: copy.id }));
  },
  setRuntime: (id, state) =>
    set((s) => {
      if (!s.charts.some((c) => c.id === id)) return s;
      const runtime = { ...s.runtime };
      if (state) runtime[id] = state;
      else delete runtime[id];
      return { runtime };
    }),
}));
useWorkspace.subscribe((state, previous) => {
  if (
    state.charts === previous.charts &&
    state.selectedId === previous.selectedId
  )
    return;
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        version: 1,
        charts: state.charts,
        selectedId: state.selectedId,
      }),
    );
    if (state.persistenceError)
      useWorkspace.setState({ persistenceError: null });
  } catch {
    if (!state.persistenceError)
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
  if (runtime) return runtime.status;
  return validation(product, chart.dataSpec).length
    ? "unconfigured"
    : "ready_to_request";
}
export function appliedChanged(chart: ChartSpec) {
  return (
    chart.appliedDataSpec &&
    hashKey([chart.appliedDataSpec]) !== hashKey([chart.dataSpec])
  );
}
export type { DataSpec };
