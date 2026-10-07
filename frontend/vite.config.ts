import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    fileParallelism: false,
    maxWorkers: 1,
    include: ["tests/all.test.ts"],
  },
});
