/** Bounded, best-effort browser telemetry. Delivery failures never enter this logger. */
type Level = "DEBUG" | "INFO" | "WARNING" | "ERROR" | "CRITICAL";
type Fields = {
  request_id?: string;
  job_id?: string;
  run_id?: string;
  duration_ms?: number;
  error?: { type: string; message: string; code?: string; stack?: string };
  context?: Record<string, string | number | boolean | null>;
};
export const apiBase = (import.meta.env.VITE_API_BASE_URL || "").replace(
  /\/$/,
  "",
);
let apiKey = "";
/** Set from the host's auth flow; credentials are never included in events. */
export function setApiKey(value: string) {
  apiKey = value;
}
export function authHeaders(): Record<string, string> {
  return apiKey ? { "X-API-Key": apiKey } : {};
}
const levels: Level[] = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];
const minimum = Math.max(
  0,
  levels.indexOf((import.meta.env.VITE_LOG_LEVEL || "INFO") as Level),
);
const queue: object[] = [];
let installed = false;
let sending = false;
export function sanitize(text: string): string {
  return text
    .replace(/https?:\/\/[^\s]+/g, (url) =>
      url.includes("@") ? "[redacted URL]" : url.split(/[?#]/)[0],
    )
    .replace(/(bearer\s+)\S+/gi, "$1[redacted]")
    .replace(
      /((?:password|secret|token|api[_-]?key|authorization|cookie)\s*[=:]\s*)[^\s,;]+/gi,
      "$1[redacted]",
    )
    .replace(/[\w.+-]+@[\w.-]+\.[a-z]{2,}/gi, "[redacted email]")
    .split(apiKey || "\u0000")
    .join(apiKey ? "[redacted]" : "\u0000")
    .slice(0, 1000);
}
export function logEvent(
  level: Level,
  event: string,
  message: string,
  fields: Fields = {},
) {
  if (
    levels.indexOf(level) < minimum ||
    queue.length >= 100 ||
    import.meta.env.VITE_MOCK_API === "true"
  )
    return;
  const context = Object.fromEntries(
    Object.entries(fields.context || {})
      .slice(0, 20)
      .map(([key, value]) => [
        key,
        /password|secret|token|authorization|cookie|api.?key|email/i.test(key)
          ? "[redacted]"
          : typeof value === "string"
            ? sanitize(value).slice(0, 200)
            : value,
      ]),
  );
  queue.push({
    ...fields,
    ...(fields.error
      ? {
          error: Object.fromEntries(
            Object.entries(fields.error)
              .filter(([, value]) => value !== undefined)
              .map(([key, value]) => [
                key,
                sanitize(value!).slice(
                  0,
                  key === "type" || key === "code" ? 100 : 1000,
                ),
              ]),
          ),
        }
      : {}),
    context,
    timestamp: new Date().toISOString(),
    level,
    service: "frontend",
    module: "workspace",
    event,
    message: sanitize(message),
  });
}
export const logger = Object.fromEntries(
  levels.map((level) => [
    level.toLowerCase(),
    (event: string, message: string, fields?: Fields) =>
      logEvent(level, event, message, fields),
  ]),
) as Record<
  Lowercase<Level>,
  (event: string, message: string, fields?: Fields) => void
>;
export async function flushLogs() {
  if (sending || !queue.length) return;
  sending = true;
  // Bound bytes as well as count, including multibyte UTF-8 strings.
  const events: object[] = [];
  while (queue.length && events.length < 20) {
    if (
      new TextEncoder().encode(
        JSON.stringify({ events: [...events, queue[0]] }),
      ).length > 60_000
    )
      break;
    events.push(queue.shift()!);
  }
  try {
    await fetch(`${apiBase}/api/v1/logs`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ events }),
      keepalive: true,
      signal: AbortSignal.timeout(5000),
    });
  } catch {
    /* Deliberately drop failed batches; no recursive API logger or retries. */
  } finally {
    sending = false;
  }
}
export function errorDetails(error: Error) {
  return { type: error.name, message: error.message, stack: error.stack };
}
export function installLogging() {
  if (installed) return;
  installed = true;
  window.addEventListener("error", (event) =>
    logger.error("javascript_error", "Unhandled JavaScript error", {
      error:
        event.error instanceof Error ? errorDetails(event.error) : undefined,
      context: { detail: sanitize(event.message) },
    }),
  );
  window.addEventListener("unhandledrejection", (event) =>
    logger.error("promise_rejected", "Unhandled promise rejection", {
      error:
        event.reason instanceof Error ? errorDetails(event.reason) : undefined,
      context: {
        detail:
          event.reason instanceof Error
            ? sanitize(event.reason.message)
            : "Non-error rejection",
      },
    }),
  );
  window.addEventListener("pagehide", () => {
    void flushLogs();
  });
  setInterval(() => {
    void flushLogs();
  }, 2000);
}
