import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

export const python = process.env.TASK10_PYTHON ?? [
  resolve(import.meta.dirname, "../.venv/Scripts/python.exe"),
  resolve(import.meta.dirname, "../../../.venv/Scripts/python.exe"),
  resolve(import.meta.dirname, "../.venv/bin/python"),
  resolve(import.meta.dirname, "../../../.venv/bin/python"),
].find(existsSync) ?? "python";

export const uiPort = process.env.WAVE4_TEST_MODE === "1" ? 5219 : 5199;
export const securityPort = process.env.WAVE4_TEST_MODE === "1" ? 8217 : 8197;
export const gatePort = process.env.WAVE4_TEST_MODE === "1" ? 8218 : 8198;

export default defineConfig({
  testDir: "./e2e",
  outputDir: process.env.DEFAULT_BROWSER_EVIDENCE ?? (process.env.WAVE4_TEST_MODE === "1" ? `../.superpowers/sdd/2026-10-12-wave4-task11-delivery/evidence/default-browser-${Date.now()}` : "./test-results"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "list",
  projects: [
    { name: "learning-ui", testMatch: "learning-loop.spec.ts", use: {
      baseURL: `http://127.0.0.1:${uiPort}`, channel: "msedge", headless: true,
      locale: "zh-CN", colorScheme: "light",
    } },
    { name: "security-request", testMatch: "security.spec.ts", use: { baseURL: `http://127.0.0.1:${securityPort}` } },
  ],
  webServer: [
    { command: `npm run dev -- --host 127.0.0.1 --port ${uiPort} --strictPort`, url: `http://127.0.0.1:${uiPort}`, reuseExistingServer: false, timeout: 30_000 },
    {
    command: `"${python}" -B -m uvicorn --app-dir tests security.http_fixture:app --host 127.0.0.1 --port ${securityPort}`,
    cwd: resolve(import.meta.dirname, "../backend"),
    url: `http://127.0.0.1:${securityPort}/health`,
    reuseExistingServer: false,
    timeout: 30_000,
    env: { PYTHONDONTWRITEBYTECODE: "1" },
    },
  ],
});
