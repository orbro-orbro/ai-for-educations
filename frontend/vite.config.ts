import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  preview: process.env.KNOWBOUND_TEACHER_TEST === "1" ? {
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api/": {
        target: process.env.KNOWBOUND_API_PROXY_TARGET || "http://api:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api(?=\/)/, ""),
        proxyTimeout: 30_000,
      },
    },
  } : undefined,
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    fileParallelism: false,
    maxWorkers: 1,
    include: ["tests/all.test.ts"],
  },
});
