import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "delivery-real.spec.ts",
  outputDir: process.env.DELIVERY_BROWSER_EVIDENCE ?? `../.superpowers/sdd/2026-10-12-wave4-task11-delivery/evidence/delivery-browser-${Date.now()}`,
  workers: 1,
  retries: 0,
  timeout: 240_000,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5209", channel: "msedge", headless: true, locale: "zh-CN", trace: "off", video: "off" },
});
