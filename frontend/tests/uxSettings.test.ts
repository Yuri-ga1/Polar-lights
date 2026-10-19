import { describe, expect, it, vi } from "vitest";
import catalog from "../src/mocks/catalog.json";
import {
  defaults,
  productSchema,
  requestParameters,
  validation,
} from "../src/api/contracts";
import {
  parsePreset,
  serializePreset,
  defaultStyle,
  workspaceSchema,
} from "../src/workspace/schema";
import {
  physicalSizeInches,
  validateExportSize,
  withPngDpi,
} from "../src/exportSizing";
import { renderSpecSchema } from "../src/api/renderJobs";
import { actionableError, jobProgress } from "../src/jobFeedback";
import { ApiError } from "../src/api/client";
import { isFutureUtcDate, latestUtcDateTime } from "../src/dateLimits";
import { rangeTimestamps } from "../src/renderRanges";

const map = productSchema.parse(
  catalog.products.find((p) => p.productId === "roti-map"),
);

describe("map sampling", () => {
  it("retains presets and validates exact custom integer strides", () => {
    const data = defaults(map);
    expect(data.resolution).toBe("full");
    expect(data.samplingStride).toBeUndefined();
    expect(validation(map, { ...data, samplingStride: 2 })).toEqual([]);
    for (const invalid of [0, -1, 2.5, 1025, "2"])
      expect(
        validation(map, { ...data, samplingStride: invalid }),
      ).toContainEqual(expect.stringContaining("samplingStride"));
    expect(
      requestParameters(map, { ...data, samplingStride: 8 }),
    ).toHaveProperty("samplingStride", 8);
  });

  it("keeps sampling in saved workspaces separately from appearance", () => {
    const chart = {
      id: "map-1",
      productId: "roti-map",
      dataSpec: { ...defaults(map), samplingStride: 32 },
      styleSpec: defaultStyle("ROTI", "roti-map"),
      layoutSpec: { x: 0, y: 0, width: 560, height: 380 },
    };
    const workspace = workspaceSchema.parse({ charts: [chart] });
    const restored = parsePreset(JSON.parse(serializePreset(workspace)));
    expect(restored.charts[0].dataSpec.samplingStride).toBe(32);
    expect(restored.charts[0].styleSpec).toEqual(chart.styleSpec);
  });
  it("separates batch render specs and cache identities by custom stride", () => {
    const base = {
      productId: "roti-map",
      timestamps: ["2026-01-19T00:00:00.000Z"],
      width: 1200,
      height: 700,
      center: [0, 0],
      zoom: 0,
      minimum: 0,
      maximum: 1,
      resolution: "low",
      maplibreVersion: "5.6.1",
      playwrightVersion: "1.55.0",
      dpr: 1,
      assetVersion: "a".repeat(64),
    };
    const two = renderSpecSchema.parse({ ...base, samplingStride: 2 });
    const eight = renderSpecSchema.parse({ ...base, samplingStride: 8 });
    expect(JSON.stringify(two)).not.toBe(JSON.stringify(eight));
    expect(
      renderSpecSchema.safeParse({ ...base, samplingStride: 0 }).success,
    ).toBe(false);
  });
});

describe("export sizing", () => {
  it("rejects malformed and oversized pixel dimensions", () => {
    expect(
      validateExportSize({ width: 2400, height: 1600, dpi: 300 }),
    ).toBeUndefined();
    expect(validateExportSize({ width: 8000, height: 5000, dpi: 300 })).toMatch(
      /32 megapixels/,
    );
    expect(validateExportSize({ width: 100.5, height: 800, dpi: 300 })).toMatch(
      /whole numbers/,
    );
  });
  it("keeps landscape and portrait PDF physical sizes tied to selected DPI", () => {
    expect(physicalSizeInches({ width: 2400, height: 1600, dpi: 300 })).toEqual(
      [8, 1600 / 300],
    );
    expect(physicalSizeInches({ width: 1600, height: 2400, dpi: 300 })).toEqual(
      [1600 / 300, 8],
    );
  });
  it("writes PNG pHYs pixels-per-metre for print DPI", () => {
    const png = new Uint8Array(45);
    png.set([137, 80, 78, 71, 13, 10, 26, 10]);
    const result = withPngDpi(png, 300);
    expect(new TextDecoder().decode(result.subarray(37, 41))).toBe("pHYs");
    expect(new DataView(result.buffer).getUint32(41)).toBe(11811);
    expect(result.length).toBe(66);
  });
});

describe("job feedback", () => {
  it("explains waiting, retries, queue limits and expired jobs without percentages", () => {
    expect(jobProgress("waiting_external")).toMatch(/SIMuRG/);
    expect(jobProgress("retrying", 3)).toMatch(/attempt 3/);
    expect(actionableError(new ApiError("QUEUE_FULL", "Queue full"))).toMatch(
      /retry/,
    );
    expect(
      actionableError(new ApiError("JOB_NOT_FOUND", "Unknown job")),
    ).toMatch(/expired/);
  });
});

describe("UTC date limit", () => {
  it("allows any time today and rejects future dates in chart and render requests", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-19T12:00:00Z"));
    try {
      expect(latestUtcDateTime()).toBe("2026-10-19T23:59:59");
      expect(isFutureUtcDate("2026-10-19T23:59:59")).toBe(false);
      expect(isFutureUtcDate("2026-10-20T00:00:00")).toBe(true);
      const data = defaults(map);
      expect(
        validation(map, { ...data, timestamp: "2026-10-19T23:59:59Z" }),
      ).toEqual([]);
      expect(
        validation(map, { ...data, timestamp: "2026-10-20T00:00:00Z" }),
      ).toContain("timestamp cannot be later than today (UTC)");
      expect(
        rangeTimestamps(
          [{ start: "2026-10-19T23:59:30", end: "2026-10-19T23:59:30" }],
          30,
        ),
      ).toHaveLength(1);
      expect(() =>
        rangeTimestamps(
          [{ start: "2026-10-20T00:00:00", end: "2026-10-20T00:00:00" }],
          30,
        ),
      ).toThrow(/later than today/);
      const renderSpec = {
        productId: "roti-map",
        timestamps: ["2026-10-20T00:00:00.000Z"],
        width: 1200,
        height: 700,
        center: [0, 0],
        zoom: 0,
        minimum: 0,
        maximum: 1,
        resolution: "full",
        maplibreVersion: "5.6.1",
        playwrightVersion: "1.55.0",
        dpr: 1,
        assetVersion: "a".repeat(64),
      };
      expect(renderSpecSchema.safeParse(renderSpec).success).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });
});
