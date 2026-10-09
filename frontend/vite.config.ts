import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    hmr: { overlay: false },
    proxy: {
      "/api": {
        target: process.env.POLAR_BACKEND_URL || "http://localhost:8000",
        changeOrigin: false, // Preserve browser Host for telemetry Origin validation.
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
  },
});
