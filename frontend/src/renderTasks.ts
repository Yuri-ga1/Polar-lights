import { create } from "zustand";
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
export const useRenderTasks = create<{ tasks: Record<string, Task> }>(() => ({
  tasks: {},
}));
const controllers = new Map<string, AbortController>();
export function cancelRender(id: string) {
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
  } catch (error) {
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
