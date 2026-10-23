import type { DownloadProgress as Progress } from "../api/contracts";

function bytes(value: number) {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(
    units.length - 1,
    Math.floor(Math.log(Math.max(1, value)) / Math.log(1024)),
  );
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}
function duration(seconds: number) {
  if (seconds < 60) return `${Math.max(1, Math.ceil(seconds))} s`;
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h ${Math.ceil((seconds % 3600) / 60)} min`;
}
export function DownloadProgress({ progress }: { progress: Progress }) {
  const { bytesDownloaded: downloaded, totalBytes: total } = progress;
  const known = total != null && total > 0;
  const complete = known && downloaded >= total;
  const stale = Date.now() / 1000 - progress.updatedAt > 10;
  const rate = stale ? null : progress.bytesPerSecond;
  const eta = stale ? null : progress.etaSeconds;
  return (
    <div className="download-progress">
      <progress
        aria-label="Download progress"
        max={known ? total : undefined}
        value={known ? Math.min(downloaded, total) : undefined}
      />
      <div className="download-metrics">
        <span>
          {bytes(downloaded)}
          {known
            ? ` / ${bytes(total)} · ${Math.min(100, (downloaded / total) * 100).toFixed(1)}%`
            : " downloaded"}
        </span>
        {rate != null && rate > 0 && <span>{bytes(rate)}/s</span>}
      </div>
      <small>
        {complete
          ? "Download received; preparing data…"
          : eta != null
            ? `About ${duration(eta)} remaining for download`
            : stale
              ? "Waiting for download activity…"
              : known
                ? "Estimating remaining download time…"
                : "Total size unknown; remaining time unavailable"}
      </small>
    </div>
  );
}
