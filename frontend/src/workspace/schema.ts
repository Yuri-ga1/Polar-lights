import { z } from "zod";
const number = z.number().finite();
const text = z.string().max(500);
export const hex = z.string().regex(/^#[0-9a-fA-F]{6}$/);
export const rectSchema = z.object({
  x: number.min(0).max(20000),
  y: number.min(0).max(20000),
  width: number.min(320).max(4000),
  height: number.min(260).max(4000),
});
export const colorbarSchema = z.object({
  visible: z.boolean().default(true),
  orientation: z.enum(["horizontal", "vertical"]).default("horizontal"),
  x: number.min(0).max(90).default(3),
  y: number.min(0).max(90).default(3),
  length: number.min(40).max(600).default(140),
  thickness: number.min(4).max(60).default(10),
  reverse: z.boolean().default(false),
  stops: z
    .array(z.object({ at: number.min(0).max(1), color: hex }))
    .max(32)
    .default([]),
  range: z.enum(["auto", "manual"]).default("auto"),
  mode: z.enum(["continuous", "discrete"]).default("continuous"),
  levels: z.number().int().min(2).max(32).default(7),
  under: hex.default("#233b75"),
  over: hex.default("#d7191c"),
  noData: hex.default("#999999"),
  title: text.default(""),
  units: text.default(""),
  ticks: z.array(number).max(32).default([]),
  font: text.default("system-ui"),
  fontSize: number.min(8).max(32).default(10),
});
export const styleSchema = z.object({
  title: text,
  subtitle: text.default(""),
  legend: z.boolean(),
  palette: z.enum(["viridis", "plasma", "ice"]),
  vmin: number.optional(),
  vmax: number.optional(),
  axes: z.boolean().default(true),
  grid: z.boolean().default(true),
  font: z.enum(["system-ui", "serif", "monospace"]).default("system-ui"),
  fontSize: number.min(8).max(40).default(12),
  labelSize: number.min(8).max(40).default(11),
  background: hex.default("#ffffff"),
  lineWidth: number.min(0.5).max(12).default(2),
  lineDash: z.enum(["solid", "dot", "dash", "dashdot"]).default("solid"),
  markers: z.boolean().default(false),
  markerSize: number.min(1).max(30).default(5),
  markerSymbol: z
    .enum(["circle", "square", "diamond", "cross"])
    .default("circle"),
  xLabel: text.default("Time (UTC)"),
  yLabel: text.default(""),
  xMin: text.default(""),
  xMax: text.default(""),
  yMin: number.optional(),
  yMax: number.optional(),
  margins: z
    .object({
      l: number.min(0).max(200).default(65),
      r: number.min(0).max(200).default(28),
      t: number.min(0).max(200).default(15),
      b: number.min(0).max(200).default(48),
    })
    .default({}),
  modebar: z.boolean().default(true),
  scrollZoom: z.boolean().default(false),
  colorbar: colorbarSchema.default({}),
  map: z
    .object({
      projection: z
        .enum(["geographic", "north-polar", "south-polar"])
        .default("geographic"),
      coastline: z.boolean().default(true),
      graticule: z.boolean().default(false),
      labels: z.boolean().default(true),
      pointSize: number.min(1).max(30).default(3),
      opacity: number.min(0).max(1).default(0.85),
      longitude: number.min(-180).max(180).default(0),
      latitude: number.min(-85).max(85).default(45),
      zoom: number.min(0).max(10).default(0.7),
      bearing: number.min(-180).max(180).default(0),
      pitch: number.min(0).max(60).default(0),
      polarX: number.min(-1000).max(1000).default(0),
      polarY: number.min(-1000).max(1000).default(0),
    })
    .default({}),
});
export const dataSchema = z.record(
  z.string().max(100),
  z.union([z.string().max(500), number, z.array(z.string().max(100)).max(64)]),
);
export const chartSchema = z.object({
  id: z.string().min(1).max(100),
  productId: z.string().min(1).max(100),
  dataSpec: dataSchema,
  appliedDataSpec: dataSchema.optional(),
  styleSpec: styleSchema,
  layoutSpec: rectSchema.extend({
    z: number.default(0),
    locked: z.boolean().default(false),
    groupId: z.string().max(100).optional(),
    free: rectSchema.optional(),
  }),
});
export type ChartSpec = z.infer<typeof chartSchema>;
export type StyleSpec = ChartSpec["styleSpec"];
export type Rect = z.infer<typeof rectSchema>;
export const workspaceSchema = z
  .object({
    charts: z.array(chartSchema).max(200),
    selectedIds: z.array(z.string()).max(200).default([]),
    mode: z.enum(["free", "grid"]).default("free"),
    snap: z.boolean().default(false),
    gridColumns: z.number().int().min(1).max(6).default(2),
  })
  .superRefine((w, ctx) => {
    if (new Set(w.charts.map((c) => c.id)).size !== w.charts.length)
      ctx.addIssue({ code: "custom", message: "Duplicate chart IDs" });
    if (w.selectedIds.some((id) => !w.charts.some((c) => c.id === id)))
      ctx.addIssue({
        code: "custom",
        message: "Selection references an unknown chart",
      });
  });
export type WorkspaceSpec = z.infer<typeof workspaceSchema>;
export const presetSchema = z.object({
  schemaVersion: z.literal(2),
  workspace: workspaceSchema,
});
export function parsePreset(input: unknown): WorkspaceSpec {
  const envelope = z
    .object({
      schemaVersion: z.number().optional(),
      version: z.number().optional(),
      workspace: z.unknown().optional(),
    })
    .passthrough()
    .parse(input);
  if (envelope.schemaVersion === 2) return presetSchema.parse(input).workspace;
  if (
    (envelope.schemaVersion === undefined && envelope.version === 1) ||
    envelope.schemaVersion === 1
  ) {
    const old = z
      .object({
        charts: z.array(z.unknown()),
        selectedId: z.string().nullish(),
      })
      .parse(envelope.workspace ?? input);
    const charts = old.charts.map((c, i) => {
      const raw = z
        .object({
          styleSpec: z
            .object({
              legend: z.boolean(),
              vmin: number.optional(),
              vmax: number.optional(),
            })
            .passthrough(),
          layoutSpec: z.record(z.unknown()),
        })
        .passthrough()
        .parse(c);
      return {
        ...raw,
        styleSpec: {
          ...raw.styleSpec,
          colorbar: {
            visible: raw.styleSpec.legend,
            range:
              raw.styleSpec.vmin != null || raw.styleSpec.vmax != null
                ? "manual"
                : "auto",
          },
        },
        layoutSpec: { ...raw.layoutSpec, z: i },
      };
    });
    return workspaceSchema.parse({
      charts,
      selectedIds: old.selectedId ? [old.selectedId] : [],
    });
  }
  throw new Error("Unsupported workspace schema version");
}
export function serializePreset(workspace: WorkspaceSpec) {
  return JSON.stringify(
    { schemaVersion: 2, workspace: workspaceSchema.parse(workspace) },
    null,
    2,
  );
}
export function emptyWorkspace(): WorkspaceSpec {
  return workspaceSchema.parse({ charts: [] });
}
export function defaultStyle(title: string): StyleSpec {
  return styleSchema.parse({ title, legend: true, palette: "viridis" });
}
