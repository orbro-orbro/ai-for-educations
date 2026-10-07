import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const python = process.env.TASK10_PYTHON ?? [
  resolve(import.meta.dirname, "../.venv/Scripts/python.exe"),
  resolve(import.meta.dirname, "../../../.venv/Scripts/python.exe"),
  resolve(import.meta.dirname, "../.venv/bin/python"),
  resolve(import.meta.dirname, "../../../.venv/bin/python"),
].find(existsSync) ?? "python";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  projects: [
    { name: "learning-ui", testMatch: "learning-loop.spec.ts", use: {
      baseURL: "http://127.0.0.1:5199", channel: "msedge", headless: true,
      locale: "zh-CN", colorScheme: "light",
    } },
    { name: "security-request", testMatch: "security.spec.ts", use: { baseURL: "http://127.0.0.1:8197" } },
  ],
  webServer: [
    { command: "npm run dev -- --host 127.0.0.1 --port 5199 --strictPort", url: "http://127.0.0.1:5199", reuseExistingServer: false, timeout: 30_000 },
    {
    command: `"${python}" -B -m uvicorn --app-dir tests security.http_fixture:app --host 127.0.0.1 --port 8197`,
    cwd: resolve(import.meta.dirname, "../backend"),
    url: "http://127.0.0.1:8197/health",
    reuseExistingServer: false,
    timeout: 30_000,
    env: { PYTHONDONTWRITEBYTECODE: "1" },
    },
  ],
});
