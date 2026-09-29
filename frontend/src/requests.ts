import { apiClient, queryClient } from "./api/client";
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
      queryClient.getQueryData<Awaited<ReturnType<typeof apiClient.data>>>(key);
    const state = queryClient.getQueryState(key);
    const result =
      cached && state && Date.now() - state.dataUpdatedAt < 60_000
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
    queryClient.setQueryData(key, result);
    useWorkspace.getState().update(id, { appliedDataSpec: parameters });
    useWorkspace.getState().setRuntime(id, { status: "loaded", result });
  } catch (error) {
    if (current())
      useWorkspace.getState().setRuntime(id, {
        status: "error",
        result: previous,
        error: error instanceof Error ? error.message : "Request failed",
      });
  } finally {
    if (requests.get(id) === controller) requests.delete(id);
  }
}
export function removeChart(id: string) {
  cancelRequest(id);
  queryClient.removeQueries({ queryKey: ["chart-data", id] });
  useWorkspace.getState().remove(id);
}
