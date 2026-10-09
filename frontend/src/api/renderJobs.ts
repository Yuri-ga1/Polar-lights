import { z } from "zod";
import {
  ApiError,
  fetchApi,
  pause,
  rememberedJob,
  pollJob,
  pageIsLeaving,
} from "./client";
import { jobSchema } from "./contracts";
export const assetSchema = z.object({
  assetVersion: z.string().regex(/^[a-f0-9]{64}$/),
  maplibreVersion: z.literal("5.6.1"),
  playwrightVersion: z.literal("1.55.0"),
  dpr: z.literal(1),
  files: z.record(z.string()),
});
export const renderSpecSchema = z
  .object({
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
    maplibreVersion: z.literal("5.6.1"),
    playwrightVersion: z.literal("1.55.0"),
    dpr: z.literal(1),
    assetVersion: z.string().regex(/^[a-f0-9]{64}$/),
  })
  .strict()
  .refine((s) => s.maximum > s.minimum, "Maximum must exceed minimum")
  .refine((s) => {
    const days = s.timestamps.map((value) =>
      Date.parse(`${value.slice(0, 10)}T00:00:00Z`),
    );
    return Math.max(...days) - Math.min(...days) <= 2 * 24 * 60 * 60 * 1000;
  }, "Map render range cannot exceed three calendar dates");
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
    const initial = saved
      ? jobSchema.parse(JSON.parse(saved))
      : jobSchema.parse(
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
    const cancel = () => {
      if (pageIsLeaving()) return;
      rememberedJob(key, null);
      void fetchApi(path, { method: "DELETE" }).catch(() => {});
    };
    signal.addEventListener("abort", cancel, { once: true });
    if (signal.aborted) {
      cancel();
      signal.throwIfAborted();
    }
    try {
      let state = initial;
      for (;;) {
        signal.throwIfAborted();
        onStatus(state);
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
    } finally {
      signal.removeEventListener("abort", cancel);
    }
  },
};
