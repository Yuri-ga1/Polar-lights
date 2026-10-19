import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";

async function addAndBuild(page: Page, name: string, timeSeries = false) {
  await page.goto("/");
  await page
    .getByRole("button", { name: new RegExp(name, "i") })
    .first()
    .click();
  const inspector = page.locator(".parameters");
  if (timeSeries) {
    await inspector
      .locator('input[type="datetime-local"]')
      .first()
      .fill("2026-01-19T00:00");
    await inspector
      .locator('input[type="datetime-local"]')
      .nth(1)
      .fill("2026-01-19T03:00");
  } else {
    await inspector
      .locator('input[type="datetime-local"]')
      .first()
      .fill("2026-01-19T00:00");
  }
  await inspector.getByRole("button", { name: "Build chart" }).click();
  const card = page.getByTestId("chart-card").first();
  await expect(card).toHaveAttribute("data-state", "loaded", {
    timeout: 30000,
  });
  return card;
}

test("geographic and polar map readouts stay above the canvas, including export", async ({
  page,
}) => {
  const card = await addAndBuild(page, "ROTI-MAP");
  const view = card.getByTestId("map-view");
  await expect(view).toHaveAttribute("data-ready", "true", { timeout: 30000 });
  const hud = view.locator(".map-hud");
  await expect(hud).toBeVisible();
  expect(
    await hud.evaluate((element) => getComputedStyle(element).zIndex),
  ).toBe("3");
  await card.locator(".chart-export summary").click();
  const options = card.locator(".export-options");
  await options.getByLabel("Lock aspect ratio").uncheck();
  await options.getByLabel("Width (px)").fill("1800");
  await options.getByLabel("Height (px)").fill("1200");
  await options.getByLabel("Print DPI").selectOption("300");
  const download = page.waitForEvent("download");
  await card.getByRole("button", { name: "Save PNG" }).click();
  const saved = await download;
  expect(saved.suggestedFilename()).toMatch(/chart-.*\.png/);
  const png = await readFile((await saved.path())!);
  expect(png.readUInt32BE(16)).toBe(1800);
  expect(png.readUInt32BE(20)).toBe(1200);
  expect(png.toString("ascii", 37, 41)).toBe("pHYs");
  expect(png.readUInt32BE(41)).toBe(11811);
  const pdfDownload = page.waitForEvent("download");
  await card.getByRole("button", { name: "Save PDF" }).click();
  const pdf = await readFile((await (await pdfDownload).path())!);
  expect(pdf.subarray(0, 160).toString("latin1")).toMatch(
    /\/MediaBox\s*\[0 0 432\.? 288\.?\]/,
  );
  await page.getByLabel("Projection").selectOption("north-polar");
  await expect(view).toHaveAttribute("data-projection", "north-polar", {
    timeout: 30000,
  });
  await expect(view.locator(".map-hud")).toBeVisible();
});

test("aurora legend and Plotly legend remain visible", async ({ page }) => {
  const aurora = await addAndBuild(page, "Aurora observations");
  await expect(aurora.locator(".aurora-legend")).toBeVisible();
  expect(
    await aurora
      .locator(".aurora-legend")
      .evaluate((element) => getComputedStyle(element).zIndex),
  ).toBe("3");
  await page
    .getByRole("button", { name: "Remove geomagnetic latitude 1" })
    .click();
  await page.getByRole("button", { name: "Apply lines" }).click();
  await expect(page.getByText("Apply an empty list")).toBeVisible();
  await page.getByRole("button", { name: "Add geomagnetic line" }).click();
  await page.getByLabel("Geomagnetic latitude 1 (°)").fill("-45,5");
  await page.getByRole("button", { name: "Apply lines" }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: /latitude|duplicate/i }),
  ).toHaveCount(0);
  await page.reload();
  await page
    .getByRole("button", { name: /KP.*timeseries/i })
    .first()
    .click();
  const inspector = page.locator(".parameters");
  await inspector
    .locator('input[type="datetime-local"]')
    .first()
    .fill("2026-01-19T00:00");
  await inspector
    .locator('input[type="datetime-local"]')
    .nth(1)
    .fill("2026-01-19T03:00");
  await inspector.getByRole("button", { name: "Build chart" }).click();
  const kp = page.getByTestId("chart-card").last();
  await expect(kp).toHaveAttribute("data-state", "loaded", { timeout: 30000 });
  await expect(kp.locator(".plot-host .legend")).toBeVisible({
    timeout: 30000,
  });
});

test("custom sampling validates drafts and survives JSON export", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: /ROTI-MAP/i })
    .first()
    .click();
  const inspector = page.locator(".parameters");
  await inspector
    .locator('input[type="datetime-local"]')
    .first()
    .fill("2026-01-19T00:00");
  const stride = inspector.getByLabel("Custom data sampling stride");
  await stride.fill("2.5");
  await stride.blur();
  await expect(
    inspector.getByText(/samplingStride must be a whole number/),
  ).toBeVisible();
  await expect(
    inspector.getByRole("button", { name: "Build chart" }),
  ).toBeDisabled();
  await stride.fill("2");
  await stride.blur();
  await inspector.getByRole("button", { name: "Build chart" }).click();
  const card = page.getByTestId("chart-card").first();
  await expect(card).toHaveAttribute("data-state", "loaded", {
    timeout: 30000,
  });
  await expect(card.locator("footer")).toContainText("stride 2");
  await expect(card.locator("footer")).toContainText("90 points");
  const settings = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Save workspace settings JSON" })
    .click();
  const saved = JSON.parse(
    (await readFile((await (await settings).path())!)).toString(),
  );
  expect(saved.workspace.charts[0].dataSpec.samplingStride).toBe(2);
});

test("date picker and manual entry reject future UTC dates", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: /ROTI-MAP/i })
    .first()
    .click();
  const date = page.locator(".parameters input[type='datetime-local']").first();
  const today = await page.evaluate(() =>
    new Date().toISOString().slice(0, 10),
  );
  await expect(date).toHaveAttribute("max", `${today}T23:59:59`);
  const previous = await date.inputValue();
  await date.fill("2099-01-01T00:00");
  await expect(date).toHaveValue(previous);
  await expect(
    page.locator(".batch-render input[type='datetime-local']").first(),
  ).toHaveAttribute("max", `${today}T23:59:59`);
});

test("TIMESERIES renders Kp as the dedicated histogram, including storm levels", async ({
  page,
}) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: /TIMESERIES timeseries/i })
    .first()
    .click();
  const inspector = page.locator(".parameters");
  await inspector.getByLabel("columns").selectOption(["omni_bx", "kp"]);
  await inspector
    .locator('input[type="datetime-local"]')
    .first()
    .fill("2026-01-19T00:00");
  await inspector
    .locator('input[type="datetime-local"]')
    .nth(1)
    .fill("2026-01-19T06:00");
  await inspector.getByLabel("Show G3").check();
  await inspector.getByRole("button", { name: "Build chart" }).click();
  const card = page.getByTestId("chart-card").first();
  await expect(card).toHaveAttribute("data-state", "loaded", {
    timeout: 30000,
  });
  const rendered = await card.locator(".plot-host").evaluate((node) => {
    const plot = node as HTMLElement & {
      _fullData: Array<{
        type: string;
        name: string;
        yaxis: string;
        text?: string[];
      }>;
      _fullLayout: { shapes: Array<{ yref: string; y0: number }> };
    };
    return {
      traces: plot._fullData.map(({ type, name, yaxis, text }) => ({
        type,
        name,
        yaxis,
        text: Array.isArray(text) ? text.filter(Boolean).slice(0, 1) : [],
      })),
      shapes: plot._fullLayout.shapes.map(({ yref, y0 }) => ({ yref, y0 })),
    };
  });
  expect(rendered.traces).toEqual([
    expect.objectContaining({ type: "scatter", yaxis: "y" }),
    expect.objectContaining({ type: "bar", name: "Kp", yaxis: "y2" }),
  ]);
  expect(rendered.shapes).toContainEqual({ yref: "y2", y0: 7 });
});
