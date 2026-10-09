import { logger, authHeaders } from "../logging";
import { QueryClient } from "@tanstack/react-query";
import {
  acceptedSchema,
  availabilitySchema,
  catalogSchema,
  jobSchema,
  resultSchema,
  geomagneticLineSchema,
  type DataSpec,
  type Result,
} from "./contracts";
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 60_000, refetchOnWindowFocus: false },
  },
});
const base = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
export function url(path: string) {
  if (
    !path.startsWith("/api/v1/") ||
    path.includes("..") ||
    path.includes("\\")
  )
    throw new Error("Unexpected API URL");
  return `${base}${path}`;
}
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public details: unknown = {},
    public requestId?: string,
  ) {
    super(message);
  }
}
export async function fetchApi(path: string, init?: RequestInit) {
  const requestId = crypto.randomUUID();
  const headers = new Headers(init?.headers);
  Object.entries(authHeaders()).forEach(([key, value]) =>
    headers.set(key, value),
  );
  headers.set("X-Request-ID", requestId);
  let response: Response;
  try {
    response = await fetch(url(path), { ...init, headers });
  } catch (error) {
    if (!init?.signal?.aborted)
      logger.warning("api_network_failed", "API network request failed", {
        request_id: requestId,
        context: { path: path.split("?")[0] },
      });
    throw error;
  }
  if (!response.ok) {
    logger.warning("api_request_failed", "API request failed", {
      request_id: response.headers.get("X-Request-ID") || requestId,
      context: { path: path.split("?")[0], status: response.status },
    });
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      body.code || `HTTP_${response.status}`,
      body.message || response.statusText,
      body.details,
      response.headers.get("X-Request-ID") ?? undefined,
    );
  }
  return response;
}
export async function decodeResult(response: Response): Promise<Result> {
  if (response.headers.get("content-type")?.includes("apache.arrow")) {
    const { tableFromIPC } = await import("apache-arrow");
    const table = tableFromIPC(new Uint8Array(await response.arrayBuffer()));
    const metadata = Object.fromEntries(
      [...table.schema.metadata].map(([k, v]) => [k, JSON.parse(v)]),
    );
    const column = (name: string) => {
      const values = table.getChild(name);
      if (!values) throw new Error(`Arrow response is missing ${name}`);
      return Array.from({ length: values.length }, (_, i) => values.get(i));
    };
    return resultSchema.parse({
      dataType: "map",
      lat: column("lat"),
      lon: column("lon"),
      value: column("value"),
      metadata,
    });
  }
  return resultSchema.parse(await response.json());
}
export function pause(signal: AbortSignal, ms: number) {
  return new Promise<void>((resolve, reject) => {
    signal.throwIfAborted();
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("Cancelled", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}
// Store only request identities and job URLs; never credentials or result payloads.
export function rememberedJob(
  key: string,
  value?: string | null,
): string | null {
  try {
    const name = `polar-job:${base}:${key}`;
    if (value === null) localStorage.removeItem(name);
    else if (value !== undefined) localStorage.setItem(name, value);
    return localStorage.getItem(name);
  } catch {
    return null;
  }
}
export async function pollJob(path: string, signal: AbortSignal) {
  let delay = 1000;
  for (;;) {
    signal.throwIfAborted();
    try {
      return await fetchApi(path, { signal });
    } catch (error) {
      if (
        error instanceof ApiError &&
        !["HTTP_502", "HTTP_503", "HTTP_504", "STORAGE_BUSY"].includes(
          error.code,
        )
      )
        throw error;
      await pause(signal, delay);
      delay = Math.min(delay * 2, 15000);
    }
  }
}
let leavingPage = false;
window.addEventListener("pagehide", () => {
  leavingPage = true;
});
window.addEventListener("pageshow", () => {
  leavingPage = false;
});
export function pageIsLeaving() {
  return leavingPage;
}

export const apiClient = {
  catalog: async (signal?: AbortSignal) =>
    catalogSchema.parse(
      await (await fetchApi("/api/v1/catalog", { signal })).json(),
    ),
  availability: async (productId: string, signal?: AbortSignal, offset = 0) =>
    availabilitySchema.parse(
      await (
        await fetchApi(
          `/api/v1/products/${encodeURIComponent(productId)}/availability?limit=100&offset=${offset}`,
          { signal },
        )
      ).json(),
    ),
  async data(
    productId: string,
    parameters: DataSpec,
    signal: AbortSignal,
    progress: (status: string) => void = () => {},
    pollMs = 900,
  ): Promise<Result> {
    const key = JSON.stringify({ productId, parameters });
    const saved = rememberedJob(key);
    let job;
    if (saved) {
      job = acceptedSchema.parse(JSON.parse(saved));
    } else {
      const response = await fetchApi("/api/v1/data", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ productId, parameters }),
        signal,
      });
      if (response.status !== 202) return decodeResult(response);
      job = acceptedSchema.parse(await response.json());
      rememberedJob(key, JSON.stringify(job));
    }
    const cancel = () => {
      if (pageIsLeaving()) return;
      rememberedJob(key, null);
      void fetchApi(job.statusUrl, { method: "DELETE" }).catch(() => {});
    };
    signal.addEventListener("abort", cancel, { once: true });
    if (signal.aborted) {
      cancel();
      signal.throwIfAborted();
    }
    try {
      for (;;) {
        signal.throwIfAborted();
        const statusResponse = await pollJob(job.statusUrl, signal);
        const status = jobSchema.parse(await statusResponse.json());
        progress(
          `${status.stage ?? status.status}${status.attempts ? ` · attempt ${status.attempts}` : ""}`,
        );
        if (["failed", "cancelled"].includes(status.status))
          rememberedJob(key, null);
        if (status.status === "completed") {
          const result = await decodeResult(
            await pollJob(job.resultUrl, signal),
          );
          rememberedJob(key, null);
          return result;
        }
        if (status.status === "failed")
          throw new ApiError(
            status.error?.code || "JOB_FAILED",
            status.error?.message || "Job failed",
            status.error?.details,
            statusResponse.headers.get("X-Request-ID") ?? undefined,
          );
        if (status.status === "cancelled")
          throw new ApiError("JOB_CANCELLED", "Job was cancelled");
        await pause(signal, pollMs);
      }
    } catch (error) {
      if (error instanceof ApiError && error.code === "JOB_NOT_FOUND")
        rememberedJob(key, null);
      throw error;
    } finally {
      signal.removeEventListener("abort", cancel);
    }
  },
  async auroraGeomagneticLines(
    timestamp: string,
    latitudes: number[],
    signal: AbortSignal,
  ) {
    return geomagneticLineSchema.parse(
      await (
        await fetchApi("/api/v1/aurora-map/geomagnetic-lines", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ timestamp, latitudes }),
          signal,
        })
      ).json(),
    );
  },
};
