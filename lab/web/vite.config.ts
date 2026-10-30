import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 중에는 /api 를 로컬 파이썬 서버(python -m lab.server)로 넘긴다
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
});
