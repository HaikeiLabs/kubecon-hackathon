import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxies API calls to the backend (e.g. `make port-forward` on :8080).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": process.env.API_URL ?? "http://localhost:8080",
      "/health": process.env.API_URL ?? "http://localhost:8080",
    },
  },
});
