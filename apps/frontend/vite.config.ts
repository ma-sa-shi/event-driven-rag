import { defineConfig } from "vite";
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
});
