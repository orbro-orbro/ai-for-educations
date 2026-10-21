import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The public teacher entry must not publish the API's interactive documentation.
// Decode and normalize first so encoded, repeated-slash or upper-case spellings
// cannot reach the same upstream route; anything undecodable is treated as blocked.
function isApiDocumentationPath(url: string | undefined): boolean {
  try {
    const path = decodeURIComponent((url ?? "").split(/[?#]/)[0]).toLowerCase().replace(/\/{2,}/g, "/");
    return /^\/(docs|redoc|openapi)(\/|\.|$)/.test(path.replace(/^\/api(?=\/)/, ""));
  } catch {
    return true;
  }
}

export default defineConfig({
  plugins: [react()],
  preview: process.env.KNOWBOUND_TEACHER_TEST === "1" ? {
    allowedHosts: [".trycloudflare.com"],
    proxy: {
      "/api/": {
        target: process.env.KNOWBOUND_API_PROXY_TARGET || "http://api:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api(?=\/)/, ""),
        // Real model calls may take up to MODEL_TIMEOUT_SECONDS (up to 120 s in the settings).
        proxyTimeout: 125_000,
        bypass: (request) => (isApiDocumentationPath(request.url) ? false : undefined),
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
