import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * WEB_PORT/WEB_DEV_PORT: cổng preview/dev (mặc định 3000).
 * API_URL: đích proxy cho /api lúc dev/preview (mặc định backend chạy local
 * ở :8000). Container nginx (Dockerfile) dùng biến API_UPSTREAM riêng, không
 * qua Vite — proxy này chỉ áp dụng khi chạy `npm run dev`/`preview` trực tiếp.
 */
const WEB_PORT = Number(process.env.WEB_PORT ?? 3000);
const WEB_DEV_PORT = Number(process.env.WEB_DEV_PORT ?? 3000);
const API_URL = process.env.API_URL ?? "http://localhost:8000";
const proxy = { "/api": { target: API_URL, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, "") } };

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  server: { host: true, port: WEB_DEV_PORT, strictPort: true, proxy },
  preview: { host: true, port: WEB_PORT, strictPort: true, proxy },
});
