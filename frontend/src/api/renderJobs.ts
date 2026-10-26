import { z } from "zod";
import { colorbarSchema, styleSchema } from "../workspace/schema";
import {
  ApiError,
  fetchApi,
  pause,
  rememberedJob,
  pollJob,
  resumeSimurgJob,
} from "./client";
import { jobSchema } from "./contracts";
import { isFutureUtcDate } from "../dateLimits";
export const assetSchema = z.object({
  assetVersion: z.string().regex(/^[a-f0-9]{64}$/),
  maplibreVersion: z.literal("5.6.1"),
  playwrightVersion: z.literal("1.55.0"),
  dpr: z.literal(1),
  files: z.record(z.string()),
});
export const renderSpecSchema = z
  .object({
    appearance: z
      .object({
        ...styleSchema.pick({
          background: true,
          font: true,
          fontSize: true,
          labelSize: true,
          subtitle: true,
          axes: true,
        }).shape,
        colors: z
          .array(z.tuple([z.number().min(0).max(1), z.string()]))
          .min(2)
          .max(128),
        autoRange: z.boolean(),
        coastline: z.boolean(),
        graticule: z.boolean(),
        labels: z.boolean(),
        pointSize: z.number().min(1).max(30),
        opacity: z.number().min(0).max(1),
        showNoData: z.boolean(),
        showAuroraGeomagnetic: z.boolean().default(false),
        auroraGeomagneticLatitudes: z
          .array(z.number().finite().min(-90).max(90))
          .default([0]),
        showAuroraTerminator: z.boolean().default(false),
        noData: z.string(),
        colorbar: colorbarSchema.pick({
          visible: true,
          orientation: true,
          x: true,
          y: true,
          length: true,
          thickness: true,
          title: true,
          units: true,
          ticks: true,
          font: true,
          fontSize: true,
        }),
      })
      .optional(),
    productId: z.enum(["roti-map", "tec-adjusted-map", "gim-map"]),
    timestamps: z.array(z.string().datetime()).min(1).max(48),
    width: z.number().int().min(256).max(2400),
    height: z.number().int().min(256).max(1600),
    center: z.tuple([
      z.number().min(-180).max(180),
      z.number().min(-85).max(85),
    ]),
    zoom: z.number().min(0).max(10),
    minimum: z.number().finite(),
    maximum: z.number().finite(),
    resolution: z.enum(["full", "medium", "low"]),
    samplingStride: z.number().int().min(1).max(1024).nullish(),
    maplibreVersion: z.literal("5.6.1"),
    playwrightVersion: z.literal("1.55.0"),
    dpr: z.literal(1),
    assetVersion: z.string().regex(/^[a-f0-9]{64}$/),
  })
  .strict()
  .refine((s) => s.maximum > s.minimum, "Maximum must exceed minimum")
  .refine((s) => {
    if (s.productId === "gim-map") return true;
    const days = s.timestamps.map((value) =>
      Date.parse(`${value.slice(0, 10)}T00:00:00Z`),
    );
    return Math.max(...days) - Math.min(...days) <= 2 * 24 * 60 * 60 * 1000;
  }, "Map render range cannot exceed three calendar dates")
  .refine(
    (s) => s.timestamps.every((timestamp) => !isFutureUtcDate(timestamp)),
    {
      message: "Render dates cannot be later than today (UTC)",
      path: ["timestamps"],
    },
  );
export type RenderSpec = z.infer<typeof renderSpecSchema>;
export const renderFilesSchema = z.object({
  jobId: z.string(),
  status: z.string(),
  files: z.array(
    z.object({
      name: z.string(),
      url: z.string().startsWith("/api/v1/map-render-jobs/"),
    }),
  ),
});
export type RenderFiles = z.infer<typeof renderFilesSchema>;
export const renderApi = {
  assets: async (signal?: AbortSignal) =>
    assetSchema.parse(
      await (await fetchApi("/api/v1/render-assets", { signal })).json(),
    ),
  async submit(
    spec: RenderSpec,
    signal: AbortSignal,
    onStatus: (status: z.infer<typeof jobSchema>) => void,
    pollMs = 900,
  ): Promise<RenderFiles> {
    const immutable = renderSpecSchema.parse(structuredClone(spec));
    const key = `render:${JSON.stringify(immutable)}`;
    const saved = rememberedJob(key);
    let initial: z.infer<typeof jobSchema> | undefined;
    if (saved) {
      try {
        initial = jobSchema.parse(JSON.parse(saved));
      } catch {
        rememberedJob(key, null);
      }
    }
    initial ??= jobSchema.parse(
      await (
        await fetchApi("/api/v1/map-render-jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(immutable),
          signal,
        })
      ).json(),
    );
    rememberedJob(key, JSON.stringify(initial));
    const path = `/api/v1/map-render-jobs/${encodeURIComponent(initial.jobId)}`;
    // Server-side render jobs are deduplicated; local cancellation only stops
    // this chart's polling. Other clients may still need the same artifact.
    signal.throwIfAborted();
    try {
      let state = initial;
      for (;;) {
        signal.throwIfAborted();
        const needsAccess =
          state.status === "failed" &&
          ["SIMURG_EMAIL_REQUIRED", "SIMURG_LIMIT_REACHED"].includes(
            state.error?.code ?? "",
          );
        onStatus(
          needsAccess
            ? {
                ...state,
                status: "waiting_external",
                stage: state.error!.code.toLowerCase(),
              }
            : state,
        );
        if (
          state.status === "failed" &&
          ["SIMURG_EMAIL_REQUIRED", "SIMURG_LIMIT_REACHED"].includes(
            state.error?.code ?? "",
          )
        ) {
          state = await resumeSimurgJob(path, state.error!.code, signal);
          continue;
        }
        if (["failed", "cancelled"].includes(state.status))
          rememberedJob(key, null);
        if (state.status === "completed") {
          const files = renderFilesSchema.parse(
            await (await pollJob(path + "/files", signal)).json(),
          );
          rememberedJob(key, null);
          return files;
        }
        if (state.status === "failed")
          throw new ApiError(
            state.error?.code ?? "RENDER_FAILED",
            state.error?.message ?? "Rendering failed",
            state.error?.details,
          );
        if (state.status === "cancelled")
          throw new ApiError("JOB_CANCELLED", "Render job cancelled");
        await pause(signal, pollMs);
        const response = await pollJob(path, signal);
        state = jobSchema.parse(await response.json());
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "JOB_NOT_FOUND")
        rememberedJob(key, null);
      throw error;
    }
  },
};
