import { afterEach, describe, expect, it, vi } from "vitest";
import { freezeMapCanvases } from "../../src/exports";
import { drawOrder } from "../../src/visualizations/colors";
import { pickedOriginalIndex } from "../../src/visualizations/picking";

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

describe("map layers", () => {
  it("draws larger values last and resolves a picked point to its original row", () => {
    const order = drawOrder([8, null, 2, 5], false);
    expect(Array.from(order)).toEqual([2, 3, 0]);
    expect(pickedOriginalIndex({ index: 2 }, order)).toBe(0);
    expect(pickedOriginalIndex({ index: 0, object: 2 }, order)).toBe(2);
    expect(pickedOriginalIndex({ index: -1 }, order)).toBeNull();
    expect(Array.from(drawOrder([8, null, 2], true))).toEqual([1, 2, 0]);
  });

  it("captures the Deck canvas inside MapLibre controls and restores it", () => {
    const host = document.createElement("div");
    host.className = "map-host";
    const controls = document.createElement("div");
    controls.className = "maplibregl-control-container";
    const canvas = document.createElement("canvas");
    controls.append(canvas);
    host.append(controls);
    document.body.append(host);
    Object.defineProperty(canvas, "getContext", { value: () => null });
    vi.spyOn(canvas, "toDataURL").mockReturnValue(
      `data:image/png;base64,${"A".repeat(120)}`,
    );

    const restore = freezeMapCanvases(host);
    const image = controls.querySelector<HTMLImageElement>("[data-export-layer]");
    expect(image?.src).toContain("data:image/png;base64,");
    expect(canvas.style.visibility).toBe("hidden");
    restore();
    expect(controls.querySelector("[data-export-layer]")).toBeNull();
    expect(canvas.style.visibility).toBe("");
  });
});
