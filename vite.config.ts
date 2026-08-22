import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  root: path.resolve(__dirname, "frontend"),
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/health": {
        target: process.env.MUNIN_API_URL || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/api": {
        target: process.env.MUNIN_API_URL || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, "frontend/dist"),
    emptyOutDir: true,
    sourcemap: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "frontend/src"),
    },
  },
});
