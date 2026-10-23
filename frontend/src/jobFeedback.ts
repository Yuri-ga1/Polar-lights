export function jobProgress(stage: string, attempts = 0): string {
  const labels: Record<string, string> = {
    simurg_email_required: "SIMuRG email required",
    simurg_limit_reached: "SIMuRG limit reached",
    cached: "Cached",
    waiting_download: "Waiting for existing download",
    queued: "Queued on the server",
    downloading: "Downloading source data",
    waiting_external: "Waiting for external SIMuRG generation",
    processing: "Preparing scientific data or rendering",
    retrying: "Retrying after a temporary failure",
    completed: "Completed",
    cancelled: "Stopped waiting",
    failed: "Failed",
  };
  return `${labels[stage] || stage}${attempts > 1 ? ` · attempt ${attempts}` : ""}`;
}

export function actionableError(error: unknown): string {
  if (
    !(error instanceof Error) ||
    !("code" in error) ||
    typeof error.code !== "string"
  )
    return error instanceof Error ? error.message : "Request failed.";
  const code = error.code;
  const guidance: Record<string, string> = {
    QUEUE_FULL: "Wait for running jobs to finish, then retry.",
    JOB_NOT_FOUND: "The job expired or was removed. Retry to start a new job.",
    INVALID_REQUEST: /point limit|byte limit/i.test(error.message)
      ? "Increase data sampling stride, then build again."
      : "Review the indicated fields and retry.",
    RENDER_ASSET_MISMATCH:
      "Reload the page to refresh render assets, then retry.",
  };
  return `${error.message}${guidance[code] ? ` ${guidance[code]}` : ""}`;
}
