import { installLogging, logger, errorDetails } from "./logging";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { queryClient } from "./api/client";
import "./styles.css";
import "./advanced.css";
async function start() {
  installLogging();
  if (import.meta.env.VITE_MOCK_API === "true") {
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </StrictMode>,
  );
}
void start().catch((error) => {
  logger.error("startup_failed", "Frontend startup failed", {
    error: error instanceof Error ? errorDetails(error) : undefined,
  });
  document.getElementById("root")!.textContent =
    `Startup failed: ${error.message}`;
});
