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
