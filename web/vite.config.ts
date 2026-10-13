import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development /api is proxied to the FastAPI service; in Compose nginx does the same.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: API_URL, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
