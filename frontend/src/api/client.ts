import { QueryClient } from "@tanstack/react-query";
import {
  acceptedSchema,
  availabilitySchema,
  catalogSchema,
  jobSchema,
  resultSchema,
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
  const response = await fetch(url(path), init);
  if (!response.ok) {
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
    const response = await fetchApi("/api/v1/data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ productId, parameters }),
      signal,
    });
    if (response.status !== 202) return decodeResult(response);
    const job = acceptedSchema.parse(await response.json());
    const cancel = () => {
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
        const statusResponse = await fetchApi(job.statusUrl, { signal });
        const status = jobSchema.parse(await statusResponse.json());
        progress(status.status);
        if (status.status === "completed")
          return await decodeResult(await fetchApi(job.resultUrl, { signal }));
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
    } finally {
      signal.removeEventListener("abort", cancel);
    }
  },
};
