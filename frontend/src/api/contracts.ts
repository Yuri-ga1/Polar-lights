import { z } from "zod";
export const parameterSchema = z.object({
  name: z.string(),
  type: z.enum(["datetime", "select", "multiselect"]),
  required: z.boolean(),
  default: z.union([z.string(), z.number(), z.array(z.string())]).nullish(),
  values: z.array(z.union([z.string(), z.number()])).nullish(),
});
export const productSchema = z.object({
  productId: z.string(),
  title: z.string(),
  category: z.string(),
  graphType: z.enum(["timeseries", "map", "keogram"]),
  available: z.boolean(),
  units: z.union([z.string(), z.record(z.string())]),
  parameterSchema: z.array(parameterSchema),
  capabilities: z.record(z.boolean()),
  availabilityStrategy: z.string(),
  remoteAcquisition: z.boolean(),
  columnMetadata: z.record(z.record(z.unknown())).default({}),
  description: z.string().optional(),
});
export const catalogSchema = z.object({ products: z.array(productSchema) });
const columnMeta = z
  .object({
    units: z.string().optional(),
    frequencySeconds: z.number().optional(),
    offsetSeconds: z.number().optional(),
    missingCount: z.number().optional(),
    missingIntervals: z.array(z.array(z.string())).optional(),
  })
  .passthrough();
export const metadataSchema = z
  .object({
    timestamp: z.string().optional(),
    units: z.union([z.string(), z.record(z.string())]).optional(),
    resolution: z.string().optional(),
    datasetVersion: z.string().optional(),
    pointCount: z.number().optional(),
    missingData: z.number().optional(),
    partial: z.boolean().optional(),
    nullPolicy: z.record(z.string()).optional(),
    columnMetadata: z.record(columnMeta).optional(),
  })
  .passthrough();
const numbers = z.array(z.number().nullable());
export const resultSchema = z.discriminatedUnion("dataType", [
  z.object({
    dataType: z.literal("aurora"),
    observations: z.array(
      z.object({
        lat: z.number(),
        lon: z.number(),
        colors: z.array(z.string()),
        sectorColors: z.array(z.string()),
        time: z.string(),
        durationMinutes: z.number(),
        forms: z.string(),
      }),
    ),
    overlays: z.object({
      terminator: z.array(z.array(z.tuple([z.number(), z.number()]))),
      nightPolygons: z.array(z.array(z.tuple([z.number(), z.number()]))),
    }),
    metadata: metadataSchema,
  }),
  z.object({
    dataType: z.literal("map"),
    lat: z.array(z.number()),
    lon: z.array(z.number()),
    value: numbers,
    metadata: metadataSchema,
  }),
  z.object({
    dataType: z.literal("timeseries"),
    time: z.array(z.string()),
    columns: z.record(numbers),
    metadata: metadataSchema,
  }),
  z.object({
    dataType: z.literal("keogram"),
    time: z.array(z.string()),
    latitude: z.array(z.number()),
    values: z.array(numbers),
    metadata: metadataSchema,
  }),
]);
export const acceptedSchema = z.object({
  jobId: z.string(),
  statusUrl: z.string(),
  resultUrl: z.string(),
});
export const jobSchema = z.object({
  jobId: z.string(),
  status: z.enum([
    "queued",
    "downloading",
    "processing",
    "completed",
    "failed",
    "cancelled",
  ]),
  resultUrl: z.string(),
  error: z
    .object({
      code: z.string(),
      message: z.string(),
      details: z.record(z.unknown()),
    })
    .nullish(),
});
export const availabilitySchema = z
  .object({
    productId: z.string(),
    timestamps: z.array(z.string()).default([]),
    dates: z.array(z.string()).default([]),
    columns: z.array(z.string()).default([]),
    intervals: z
      .array(
        z.object({ column: z.string(), start: z.string(), end: z.string() }),
      )
      .default([]),
    total: z.number(),
    nextOffset: z.number().nullable(),
    datasetVersion: z.string(),
    generatedAt: z.string(),
    source: z.union([z.string(), z.array(z.string())]),
  })
  .passthrough();
export type Product = z.infer<typeof productSchema>;
export type Parameter = z.infer<typeof parameterSchema>;
export type Result = z.infer<typeof resultSchema>;
export type MapResult = Extract<Result, { dataType: "map" }>;
export type AuroraResult = Extract<Result, { dataType: "aurora" }>;
export const geomagneticLineSchema = z.object({
  lines: z.array(
    z.object({
      latitude: z.number(),
      paths: z.array(z.array(z.tuple([z.number(), z.number()]))),
    }),
  ),
});
export type DataSpec = Record<string, string | number | string[]>;
export function defaults(product: Product): DataSpec {
  return Object.fromEntries(
    product.parameterSchema
      .filter((p) => p.default != null || p.type === "datetime")
      .map((p) => [
        p.name,
        p.default != null
          ? structuredClone(p.default)
          : `${new Date().toISOString().slice(0, 10)}T00:00:00Z`,
      ]),
  );
}
export function validation(product: Product, data: DataSpec): string[] {
  const errors: string[] = [];
  for (const p of product.parameterSchema) {
    const value = data[p.name];
    if (
      value == null ||
      value === "" ||
      (Array.isArray(value) && !value.length)
    ) {
      if (p.required) errors.push(`${p.name} is required`);
      continue;
    }
    if (
      p.type === "datetime" &&
      (typeof value !== "string" ||
        !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(value) ||
        !Number.isFinite(Date.parse(value)))
    )
      errors.push(`${p.name} must be a UTC date and time`);
    if (
      p.type === "select" &&
      p.values &&
      !p.values.includes(value as string | number)
    )
      errors.push(`${p.name} has an invalid value`);
    if (
      p.type === "multiselect" &&
      (!Array.isArray(value) || value.some((v) => !p.values?.includes(v)))
    )
      errors.push(`${p.name} has invalid selections`);
  }
  if (
    typeof data.start === "string" &&
    typeof data.end === "string" &&
    data.end < data.start
  ) {
    errors.push("end must be on or after start");
  } else if (
    typeof data.start === "string" &&
    typeof data.end === "string" &&
    Number.isFinite(Date.parse(data.start)) &&
    Number.isFinite(Date.parse(data.end))
  ) {
    if (product.graphType === "keogram") {
      const start = Date.parse(`${data.start.slice(0, 10)}T00:00:00Z`);
      const end = Date.parse(`${data.end.slice(0, 10)}T00:00:00Z`);
      if (end - start > 2 * 24 * 60 * 60 * 1000)
        errors.push("Map range cannot exceed three calendar dates");
    } else if (
      product.graphType === "timeseries" &&
      Date.parse(data.end) - Date.parse(data.start) > 31 * 24 * 60 * 60 * 1000
    ) {
      errors.push("Time-series range cannot exceed 31 days");
    }
  }
  return errors;
}
// Build only the schema-declared parameters. No chartId or UI properties cross the API boundary.
export function requestParameters(product: Product, data: DataSpec): DataSpec {
  return Object.fromEntries(
    product.parameterSchema
      .filter((p) => data[p.name] !== undefined && data[p.name] !== "")
      .map((p) => [p.name, data[p.name]]),
  );
}
