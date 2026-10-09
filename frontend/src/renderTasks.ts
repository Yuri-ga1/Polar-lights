import { logger } from "./logging";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { ApiError } from "./api/client";
import { renderApi, type RenderSpec, type RenderFiles } from "./api/renderJobs";
import { useWorkspace } from "./store";
type Task = {
  status: string;
  spec: RenderSpec;
  files?: RenderFiles;
  error?: string;
  requestId?: string;
};
export const useRenderTasks = create<{ tasks: Record<string, Task> }>()(
  persist(() => ({ tasks: {} }), {
    name: `polar-render-tasks:${import.meta.env.VITE_API_BASE_URL || ""}`,
    version: 1,
  }),
);
const controllers = new Map<string, AbortController>();
export function resumeRender(id: string) {
  const task = useRenderTasks.getState().tasks[id];
  if (
    task &&
    !controllers.has(id) &&
    [
      "queued",
      "downloading",
      "processing",
      "waiting_external",
      "retrying",
    ].includes(task.status)
  )
    void startRender(id, task.spec);
}
export function cancelRender(id: string) {
  if (controllers.has(id))
    logger.info("render_cancelled", "Render operation cancelled");
  controllers.get(id)?.abort();
  controllers.delete(id);
  const task = useRenderTasks.getState().tasks[id];
  if (task)
    useRenderTasks.setState((s) => ({
      tasks: { ...s.tasks, [id]: { ...task, status: "cancelled" } },
    }));
}
export async function startRender(id: string, spec: RenderSpec) {
  cancelRender(id);
  const began = performance.now();
  logger.info("render_started", "Render operation started");
  const immutable = Object.freeze(structuredClone(spec));
  const controller = new AbortController();
  controllers.set(id, controller);
  const update = (patch: Partial<Task>) => {
    if (controllers.get(id) === controller && !controller.signal.aborted)
      useRenderTasks.setState((s) => ({
        tasks: {
          ...s.tasks,
          [id]: { ...s.tasks[id], spec: immutable, ...patch },
        },
      }));
  };
  update({ status: "queued", files: undefined, error: undefined });
  try {
    const files = await renderApi.submit(
      immutable,
      controller.signal,
      (status) => update({ status: status.status }),
    );
    update({ status: "completed", files });
    logger.info("render_completed", "Render operation completed", {
      duration_ms: performance.now() - began,
    });
  } catch (error) {
    if (!controller.signal.aborted)
      logger.warning("render_failed", "Render operation failed", {
        request_id: error instanceof ApiError ? error.requestId : undefined,
      });
    update({
      status: "failed",
      error:
        error instanceof ApiError
          ? `${error.code}: ${error.message}`
          : "Render job could not be completed.",
      requestId: error instanceof ApiError ? error.requestId : undefined,
    });
  } finally {
    if (controllers.get(id) === controller) controllers.delete(id);
  }
}
useWorkspace.subscribe((s, p) => {
  if (s.charts === p.charts) return;
  for (const id of Object.keys(useRenderTasks.getState().tasks))
    if (!s.charts.some((c) => c.id === id)) {
      cancelRender(id);
      useRenderTasks.setState((state) => {
        const tasks = { ...state.tasks };
        delete tasks[id];
        return { tasks };
      });
    }
});
