import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API has no CORS: the browser only talks to Vite, which proxies /api.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
