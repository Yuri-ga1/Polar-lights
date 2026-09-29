import { useEffect, useRef, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { apiClient } from "../api/client";
import type { Product } from "../api/contracts";
import { useWorkspace, type ChartSpec } from "../store";
import { cancelRequest, requestChart } from "../requests";
export function Timeline({
  chart,
  product,
}: {
  chart: ChartSpec;
  product: Product;
}) {
  const pages = useInfiniteQuery({
    queryKey: ["availability-pages", product.productId],
    initialPageParam: 0,
    queryFn: ({ signal, pageParam }) =>
      apiClient.availability(product.productId, signal, pageParam),
    getNextPageParam: (last) => last.nextOffset ?? undefined,
  });
  const timestamps = [
    ...new Set(pages.data?.pages.flatMap((p) => p.timestamps) ?? []),
  ].sort();
  const [pending, setPending] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const epoch = useWorkspace((s) => s.epoch);
  useEffect(
    () => () => clearTimeout(timer.current),
    [chart.id, epoch, chart.dataSpec],
  );
  const seek = (timestamp: string) => {
    setPending(timestamp);
    cancelRequest(chart.id);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (!useWorkspace.getState().charts.some((c) => c.id === chart.id))
        return;
      const current = useWorkspace
        .getState()
        .charts.find((c) => c.id === chart.id)!;
      useWorkspace
        .getState()
        .update(chart.id, { dataSpec: { ...current.dataSpec, timestamp } });
      setPending(null);
      void requestChart(chart.id, product);
    }, 350);
  };
  return (
    <details className="availability" open>
      <summary>Data availability</summary>
      {pages.isPending ? (
        <p>Checking available observations…</p>
      ) : pages.error ? (
        <p>Availability unavailable. You can still build a chart.</p>
      ) : (
        <>
          <p>
            {pages.data.pages[0].total} local entries.{" "}
            {product.remoteAcquisition
              ? "Other dates may take longer to load."
              : "Dates outside the local index may be unavailable."}
          </p>
          {product.graphType === "map" && timestamps.length > 0 && (
            <>
              <label className="field">
                Timeline (UTC)
                <input
                  aria-label="Timeline (UTC)"
                  type="range"
                  min={0}
                  max={timestamps.length - 1}
                  value={Math.max(
                    0,
                    timestamps.indexOf(
                      pending ?? String(chart.dataSpec.timestamp),
                    ),
                  )}
                  onChange={(e) => seek(timestamps[Number(e.target.value)])}
                />
              </label>
              <output aria-live="polite">
                {pending ?? chart.dataSpec.timestamp ?? "Choose a frame"}
              </output>
              <div className="timestamp-list">
                {timestamps.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => {
                      const s = useWorkspace.getState();
                      s.update(chart.id, {
                        dataSpec: { ...chart.dataSpec, timestamp: t },
                      });
                    }}
                  >
                    {t}
                  </button>
                ))}
              </div>
              <small>
                The slider builds a frame after a short pause; clicking a date
                only fills the draft.
              </small>
            </>
          )}
          {product.graphType !== "map" &&
            pages.data.pages
              .flatMap((p) => p.intervals)
              .map((interval, i) => (
                <p key={i}>
                  {interval.column}: {interval.start} — {interval.end}
                </p>
              ))}
          {pages.hasNextPage && (
            <button
              type="button"
              disabled={pages.isFetchingNextPage}
              onClick={() => void pages.fetchNextPage()}
            >
              More available dates
            </button>
          )}
        </>
      )}
    </details>
  );
}
