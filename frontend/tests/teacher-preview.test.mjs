import assert from "node:assert/strict";
import { createServer, get } from "node:http";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { preview } from "vite";

test("teacher entry serves the web and proxies authenticated API requests on one origin", async () => {
  const upstream = createServer((request, response) => {
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ path: request.url, authorization: request.headers.authorization, method: request.method }));
  });
  await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
  process.env.KNOWBOUND_TEACHER_TEST = "1";
  process.env.KNOWBOUND_API_PROXY_TARGET = `http://127.0.0.1:${upstream.address().port}`;
  let server;
  try {
    server = await preview({ root: fileURLToPath(new URL("../", import.meta.url)), preview: { host: "127.0.0.1", port: 0 } });
    const base = `http://127.0.0.1:${server.httpServer.address().port}`;
    const page = await fetch(base);
    assert.match(await page.text(), /<html/);
    const result = await fetch(`${base}/api/me/memories?course_id=example`, { headers: { Authorization: "Bearer synthetic-test" } });
    assert.deepEqual(await result.json(), { path: "/me/memories?course_id=example", authorization: "Bearer synthetic-test", method: "GET" });
    const post = await fetch(`${base}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    assert.equal((await post.json()).method, "POST");
    const statusWithHost = (host) => new Promise((resolve, reject) => {
      get(base, { headers: { Host: host } }, (response) => { response.resume(); resolve(response.statusCode); }).on("error", reject);
    });
    assert.equal(await statusWithHost("teacher.trycloudflare.com"), 200);
    assert.equal(await statusWithHost("untrusted.example.org"), 403);
  } finally {
    delete process.env.KNOWBOUND_TEACHER_TEST;
    delete process.env.KNOWBOUND_API_PROXY_TARGET;
    if (server) await new Promise((resolve) => server.httpServer.close(resolve));
    await new Promise((resolve) => upstream.close(resolve));
  }
});

async function withTeacherPreview(run) {
  const seen = [];
  const upstream = createServer((request, response) => {
    seen.push(request.url);
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ path: request.url }));
  });
  await new Promise((resolve) => upstream.listen(0, "127.0.0.1", resolve));
  process.env.KNOWBOUND_TEACHER_TEST = "1";
  process.env.KNOWBOUND_API_PROXY_TARGET = `http://127.0.0.1:${upstream.address().port}`;
  let server;
  try {
    server = await preview({ root: fileURLToPath(new URL("../", import.meta.url)), preview: { host: "127.0.0.1", port: 0 } });
    await run({ base: `http://127.0.0.1:${server.httpServer.address().port}`, seen, server });
  } finally {
    delete process.env.KNOWBOUND_TEACHER_TEST;
    delete process.env.KNOWBOUND_API_PROXY_TARGET;
    if (server) await new Promise((resolve) => server.httpServer.close(resolve));
    await new Promise((resolve) => upstream.close(resolve));
  }
}

test("teacher entry allows a real model call to finish before the proxy gives up", async () => {
  await withTeacherPreview(async ({ server }) => {
    assert.ok(server.config.preview.proxy["/api/"].proxyTimeout >= 90_000);
  });
});

test("teacher entry never exposes API documentation but keeps normal API routes", async () => {
  await withTeacherPreview(async ({ base, seen }) => {
    const blocked = ["/api/docs", "/api/docs/", "/api/docs?x=1", "/api/redoc", "/api/openapi.json",
      "/api/DOCS", "/api/%64ocs", "/api//docs", "/api/openapi.json?x=1", "/api/docs/oauth2-redirect"];
    for (const path of blocked) {
      const response = await fetch(base + path);
      assert.equal(response.status, 404, `${path} must not reach the API`);
    }
    assert.deepEqual(seen, [], "blocked paths must never be forwarded upstream");
    const allowed = await fetch(`${base}/api/health`);
    assert.equal(allowed.status, 200);
    assert.deepEqual(seen, ["/health"]);
    const nested = await fetch(`${base}/api/courses/documents-and-docs`);
    assert.equal(nested.status, 200, "only top-level documentation paths are blocked");
  });
});