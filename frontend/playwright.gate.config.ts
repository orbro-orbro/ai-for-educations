import { defineConfig } from "@playwright/test";

// Run only after Task 9 is integrated and its UI is served on the Gate URL.
// No skip/xfail: a missing UI causes a real failure if this suite is invoked.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "security-ui.gate.ts",
  outputDir: "./test-results/security-ui-gate",
  workers: 1,
  retries: 0,
  reporter: "list",
  use: { baseURL: process.env.WAVE3_UI_URL ?? "http://127.0.0.1:5199", channel: "msedge", headless: true, locale: "zh-CN" },
});
