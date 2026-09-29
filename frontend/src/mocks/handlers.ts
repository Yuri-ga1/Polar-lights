import { http, HttpResponse, delay } from "msw";
import { tableFromArrays, tableToIPC } from "apache-arrow";
import rawCatalog from "./catalog.json";
import { catalogSchema } from "../api/contracts";
import { type DataSpec, type Result } from "../api/contracts";
const catalog = catalogSchema.parse(rawCatalog);
type Request = { productId: string; parameters: DataSpec };
const jobs = new Map<
  string,
  { request: Request; polls: number; cancelled: boolean }
>();
export function mockResult({ productId, parameters: p }: Request): Result {
  const product = catalog.products.find((x) => x.productId === productId)!;
  if (product.graphType === "map") {
    const lat = Array.from(
      { length: 180 },
      (_, i) => 40 + Math.floor(i / 30) * 6,
    );
    const lon = lat.map((_, i) => -175 + (i % 30) * 12);
    return {
      dataType: "map",
      lat,
      lon,
      value: lat.map((_, i) =>
        i % 37 === 0
          ? null
          : 0.1 +
            Math.abs(
              Math.sin(i * 0.23 + Date.parse(String(p.timestamp)) / 3600000),
            ) *
              0.9,
      ),
      metadata: {
        productId,
        timestamp: String(p.timestamp),
        units: String(product.units),
        resolution: String(p.resolution || "full"),
        pointCount: lat.length,
        missingData: 5,
        datasetVersion: "mock-v1",
        source: "SIMuRG",
        generatedAt: new Date().toISOString(),
      },
    };
  }
  const start = Date.parse(String(p.start));
  const step =
    product.graphType === "keogram"
      ? Number(p.timeStepMinutes || 5) * 60000
      : 60000;
  const end = p.end ? Date.parse(String(p.end)) : start + 19 * step;
  const time = Array.from(
    {
      length: Math.max(1, Math.min(200, Math.floor((end - start) / step) + 1)),
    },
    (_, i) => new Date(start + i * step).toISOString(),
  );
  if (product.graphType === "keogram")
    return {
      dataType: "keogram",
      time,
      latitude: [-60, -30, 0, 30, 60],
      values: Array.from({ length: 5 }, (_, j) =>
        time.map((_, i) => (i === 4 ? null : Math.abs(Math.sin(i + j)))),
      ),
      metadata: {
        units: String(product.units),
        datasetVersion: "mock-v1",
        missingTimestamps: [time[4]],
      },
    };
  const columns = (p.columns as string[]) || [];
  const units = Object.fromEntries(
    columns.map((c) => [
      c,
      typeof product.units === "object"
        ? (product.units as Record<string, string>)[c] || ""
        : "",
    ]),
  );
  const frequency = (column: string) =>
    Number(product.columnMetadata[column]?.frequencySeconds || 60);
  return {
    dataType: "timeseries",
    time,
    columns: Object.fromEntries(
      columns.map((c, j) => [
        c,
        time.map((t, i) =>
          i === 5 || (Date.parse(t) / 1000) % frequency(c) !== 0
            ? null
            : Math.sin(i * 0.4 + j) * 3 + j * 10,
        ),
      ]),
    ),
    metadata: {
      units,
      partial: true,
      datasetVersion: "mock-v1",
      columnMetadata: Object.fromEntries(
        columns.map((c) => [
          c,
          {
            units: units[c],
            frequencySeconds: frequency(c),
            offsetSeconds: 0,
            missingCount: 1,
          },
        ]),
      ),
      nullPolicy: {
        missing_data: "null at an expected sample",
        no_sample_expected: "null outside the column UTC sampling grid",
      },
    },
  };
}
function response(request: Request) {
  const result = mockResult(request);
  if (result.dataType === "map" && request.parameters.format !== "json") {
    const table = tableFromArrays({
      lat: result.lat,
      lon: result.lon,
      value: result.value,
    });
    for (const [key, value] of Object.entries(result.metadata))
      table.schema.metadata.set(key, JSON.stringify(value));
    const ipc = tableToIPC(table, "stream");
    return new HttpResponse(new Uint8Array(ipc).buffer, {
      headers: { "Content-Type": "application/vnd.apache.arrow.stream" },
    });
  }
  return HttpResponse.json(result);
}
export const handlers = [
  http.get("*/api/v1/health", () =>
    HttpResponse.json({ status: "ok", apiVersion: "1.0.0" }),
  ),
  http.get("*/api/v1/catalog", () => HttpResponse.json(catalog)),
  http.get("*/api/v1/products/:id/availability", ({ params }) =>
    HttpResponse.json({
      productId: params.id,
      columns: [],
      intervals: [],
      stations: [],
      timestamps: ["2026-01-19T00:00:00Z", "2026-01-19T01:00:00Z"],
      dates: ["2026-01-19"],
      total: 2,
      nextOffset: null,
      datasetVersion: "mock-v1",
      generatedAt: "2026-01-19T00:00:00Z",
      source: "SIMuRG",
    }),
  ),
  http.post("*/api/v1/data", async ({ request }) => {
    const body = (await request.json()) as Request;
    if (!catalog.products.some((p) => p.productId === body.productId))
      return HttpResponse.json(
        { code: "PRODUCT_NOT_FOUND", message: "Unknown product", details: {} },
        { status: 404 },
      );
    if (
      String(body.parameters.timestamp || body.parameters.start).startsWith(
        "2000-",
      )
    )
      return HttpResponse.json(
        {
          code: "DATA_NOT_AVAILABLE",
          message: "No samples available for this demo date. Use 2026-01-19.",
          details: {},
        },
        { status: 404 },
      );
    await delay(100);
    const jobId = crypto.randomUUID();
    jobs.set(jobId, { request: body, polls: 0, cancelled: false });
    return HttpResponse.json(
      {
        status: "processing",
        jobId,
        statusUrl: `/api/v1/jobs/${jobId}`,
        resultUrl: `/api/v1/jobs/${jobId}/result`,
      },
      { status: 202 },
    );
  }),
  http.get("*/api/v1/jobs/:id", ({ params }) => {
    const job = jobs.get(String(params.id));
    if (!job)
      return HttpResponse.json(
        { code: "JOB_NOT_FOUND", message: "Unknown job", details: {} },
        { status: 404 },
      );
    return HttpResponse.json({
      jobId: params.id,
      status: job.cancelled
        ? "cancelled"
        : ++job.polls > 1
          ? "completed"
          : "processing",
      createdAt: 1,
      updatedAt: 2,
      resultUrl: `/api/v1/jobs/${params.id}/result`,
    });
  }),
  http.delete("*/api/v1/jobs/:id", ({ params }) => {
    const job = jobs.get(String(params.id));
    if (job) job.cancelled = true;
    return HttpResponse.json({
      jobId: params.id,
      status: "cancelled",
      createdAt: 1,
      updatedAt: 2,
      resultUrl: `/api/v1/jobs/${params.id}/result`,
    });
  }),
  http.get("*/api/v1/jobs/:id/result", ({ params }) => {
    const job = jobs.get(String(params.id));
    return job
      ? response(job.request)
      : HttpResponse.json(
          { code: "JOB_NOT_FOUND", message: "Unknown job", details: {} },
          { status: 404 },
        );
  }),
];
