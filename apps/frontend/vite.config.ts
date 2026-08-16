import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Same-origin /api in dev, mirroring CloudFront's /api/* -> Lambda routing
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    // Vitest 4はnode_modulesと.gitしか除外しない為、対象をtest/に限定する
    include: ["test/**/*.test.{ts,tsx}"],
  },
});
