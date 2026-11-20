import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In the browser the UI only talks to Vite, which proxies /api (the desktop app calls the port directly).
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
});
