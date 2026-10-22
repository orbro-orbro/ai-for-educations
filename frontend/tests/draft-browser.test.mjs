import assert from "node:assert/strict";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";
import { preview } from "vite";

test("a student can edit offline and restore a draft in a real browser", async () => {
  const server = await preview({ root: fileURLToPath(new URL("../", import.meta.url)), configFile: false, preview: { host: "127.0.0.1", port: 0 } });
  let browser;
  try {
    browser = await chromium.launch({ channel: "msedge", headless: true });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, locale: "zh-CN" });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    let writes = 0;
    await page.route("**/*", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.port !== "8000") return route.continue();
      if (request.method() === "POST") writes++;
      const fixtures = {
        "/model-settings": { scope: "shared", provider: "mock", model: "", base_url: "", source: "environment", configured: true, key_hint: null, timeout_seconds: 30, personal_configured: false, shared: {provider: "mock", model: "", configured: true}, persistence: "memory", environment_locked: true },
        "/courses": [{ course_id: "synthetic-course", title: "仓颉语言设计 · 合成测试" }],
        "/courses/synthetic-course/exercises": [{ exercise_id: "synthetic-exercise", course_id: "synthetic-course", title: "草稿恢复体验" }],
        "/me/memory-proposals": [], "/me/memories": [],
      };
      assert.ok(url.pathname in fixtures, `Unexpected API call: ${url.pathname}`);
      await route.fulfill({ json: fixtures[url.pathname], headers: { "Access-Control-Allow-Origin": "*" } });
    });
    await page.addInitScript(() => localStorage.setItem("knowbound.session", JSON.stringify({ accessToken: "synthetic", actor: { role: "student", user_id: "synthetic-browser-student" } })));
    const base = `http://127.0.0.1:${server.httpServer.address().port}`;
    await page.goto(base);
    const editor = page.getByRole("textbox", { name: "仓颉源码" });
    await editor.waitFor();
    await page.context().setOffline(true);
    await editor.fill("// 离线写下的学习草稿\nmain() {} ");
    await page.getByText("草稿已保存到本机，尚未自动提交").waitFor();
    await page.context().setOffline(false);
    await page.reload();
    await editor.waitFor();
    assert.equal(await editor.inputValue(), "// 离线写下的学习草稿\nmain() {} ");
    assert.equal(writes, 0, "Drafts must not be submitted automatically");
    assert.deepEqual(errors, []);
    if (process.env.KNOWBOUND_SCREENSHOT_PATH) await page.screenshot({ path: process.env.KNOWBOUND_SCREENSHOT_PATH, fullPage: true });
  } finally {
    await browser?.close();
    await new Promise((resolve) => server.httpServer.close(resolve));
  }
});
