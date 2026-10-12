import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";
import { python, uiPort, gatePort } from "./playwright.config";

// Run only after Task 9 is integrated and its UI is served on the Gate URL.
// No skip/xfail: a missing UI causes a real failure if this suite is invoked.
export default defineConfig({
  testDir: "./e2e",
  projects: [
    {name:"security-ui-projection",testMatch:"security-ui.gate.ts"},
    {name:"wave3-real-ui",testMatch:"wave3-real.spec.ts"},
  ],
  outputDir: "./test-results/security-ui-gate",
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: process.env.WAVE3_UI_URL ?? `http://127.0.0.1:${uiPort}`, channel: "msedge", headless: true, locale: "zh-CN" },
  webServer: [
    {command:`npm run dev -- --host 127.0.0.1 --port ${uiPort} --strictPort`,url:`http://127.0.0.1:${uiPort}`,reuseExistingServer:false,timeout:30_000,env:{VITE_API_BASE_URL:`http://127.0.0.1:${gatePort}`}},
    {command:`"${python}" -B -m uvicorn tests.integration.wave3_browser_fixture:app --host 127.0.0.1 --port ${gatePort} --no-access-log`,cwd:resolve(import.meta.dirname,"../backend"),url:`http://127.0.0.1:${gatePort}/health`,reuseExistingServer:false,timeout:30_000,env:{PYTHONDONTWRITEBYTECODE:"1",APP_ENV:"test"}},
  ],
});
