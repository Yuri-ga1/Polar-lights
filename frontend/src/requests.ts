import { apiClient, ApiError, queryClient } from "./api/client";
import { sliceCache } from "./api/sliceCache";
import { requestParameters, validation, type Product } from "./api/contracts";
import { useWorkspace } from "./store";
const requests = new Map<string, AbortController>();
export function cancelRequest(id: string) {
  requests.get(id)?.abort();
  requests.delete(id);
  const old = useWorkspace.getState().runtime[id];
  useWorkspace
    .getState()
    .setRuntime(
      id,
      old?.result ? { status: "loaded", result: old.result } : undefined,
    );
}
export async function requestChart(id: string, product: Product) {
  const chart = useWorkspace.getState().charts.find((c) => c.id === id);
  if (
    !chart ||
    !product.available ||
    validation(product, chart.dataSpec).length
  )
    return;
  cancelRequest(id);
  const controller = new AbortController();
  requests.set(id, controller);
  const parameters = requestParameters(
    product,
    structuredClone(chart.dataSpec),
  );
  const previous = useWorkspace.getState().runtime[id]?.result;
  const current = () =>
    requests.get(id) === controller &&
    !controller.signal.aborted &&
    useWorkspace.getState().charts.some((c) => c.id === id);
  const key = ["chart-data", id, product.productId, parameters];
  useWorkspace.getState().setRuntime(id, {
    status: "loading",
    result: previous,
    progress: "Requesting data",
  });
  try {
    // Per-card keys prevent one card's cancellation from aborting another's request.
    const cached =
      product.productId === "aurora-map"
        ? undefined
        : product.graphType === "map"
          ? sliceCache.get(product.productId, parameters, id)
          : queryClient.getQueryData<Awaited<ReturnType<typeof apiClient.data>>>(
              key,
            );
    const state = queryClient.getQueryState(key);
    const result =
      cached &&
      (product.graphType === "map" ||
        (state && Date.now() - state.dataUpdatedAt < 60_000))
        ? cached
        : await apiClient.data(
            product.productId,
            parameters,
            controller.signal,
            (progress) => {
              if (current())
                useWorkspace.getState().setRuntime(id, {
                  status: "loading",
                  result: previous,
                  progress,
                });
            },
          );
    if (!current()) return;
    if (result.dataType === "map")
      sliceCache.set(product.productId, parameters, result, id);
    else {
      queryClient.removeQueries({ queryKey: ["chart-data", id] });
      queryClient.setQueryData(key, result);
    }
    useWorkspace.getState().update(id, { appliedDataSpec: parameters });
    useWorkspace.getState().setRuntime(id, { status: "loaded", result });
  } catch (error) {
    if (current())
      useWorkspace.getState().setRuntime(id, {
        status: "error",
        result: previous,
        error: error instanceof Error ? error.message : "Request failed",
        errorCode: error instanceof ApiError ? error.code : "CLIENT_ERROR",
        requestId: error instanceof ApiError ? error.requestId : undefined,
      });
  } finally {
    if (requests.get(id) === controller) requests.delete(id);
  }
}
export function removeChart(id: string) {
  useWorkspace.getState().remove(id);
}
// Deletion, undo and import all pass through this cleanup; toolbar/shortcuts cannot bypass it.
useWorkspace.subscribe((s, previous) => {
  if (s.epoch !== previous.epoch)
    for (const id of [...requests.keys()]) cancelRequest(id);
  if (s.charts === previous.charts) return;
  const removed = previous.charts.filter(
    (c) => !s.charts.some((next) => next.id === c.id),
  );
  if (!removed.length) return;
  const runtime = { ...useWorkspace.getState().runtime };
  for (const c of removed) {
    requests.get(c.id)?.abort();
    requests.delete(c.id);
    sliceCache.release(c.id);
    queryClient.removeQueries({ queryKey: ["chart-data", c.id] });
    delete runtime[c.id];
  }
  useWorkspace.setState({ runtime });
});
