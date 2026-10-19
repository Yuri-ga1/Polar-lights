import { describe, expect, it } from "vitest";
import type { Result } from "../../src/api/contracts";
import { defaultStyle } from "../../src/workspace/schema";
import {
  KP_BAR_WIDTH_MS,
  kpBarTrace,
  kpStormLines,
} from "../../src/visualizations/kp";

describe("Kp histogram", () => {
  it("uses scientific labels, storm colors, and the backend bar width", () => {
    const result: Extract<Result, { dataType: "timeseries" }> = {
      dataType: "timeseries",
      time: [
        "2026-01-19T00:00:00Z",
        "2026-01-19T03:00:00Z",
        "2026-01-19T06:00:00Z",
        "2026-01-19T09:00:00Z",
      ],
      columns: { kp: [8, 8.333, 7.667, null] },
      metadata: {},
    };
    const trace = kpBarTrace(result, "y2");
    expect(trace.type).toBe("bar");
    expect(trace.yaxis).toBe("y2");
    expect(trace.y).toEqual([8, 8.333, 7.667, null]);
    expect(trace.width).toEqual(Array(4).fill(KP_BAR_WIDTH_MS));
    expect(trace.text).toEqual(["8o", "8+", "8−", ""]);
    expect(trace.marker).toMatchObject({
      color: ["#d44545", "#d44545", "#d44545", "transparent"],
    });
    expect(kpStormLines(defaultStyle("TIMESERIES", "timeseries"))).toHaveLength(
      5,
    );
  });
});
