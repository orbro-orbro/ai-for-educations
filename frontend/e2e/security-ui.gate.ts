// Wave 3 Gate pending. UI projections use contract fixtures; real backend
// authorization must also pass security.spec.ts and Task 8 Router/SQL tests.
import { expect, test, type Page } from "@playwright/test";

const filters = { concept_id: null, exercise_id: null, start_at: null, end_at: null };
const privateMarker = "PRIVATE_MEMORY_OR_CONVERSATION_UI_SENTINEL";

async function session(page: Page, role: "student" | "teacher") {
  await page.addInitScript(nextRole => {
    if (sessionStorage.getItem("task10.fixture-seeded") === "yes") return;
    localStorage.setItem("knowbound.session", JSON.stringify({
      accessToken: "synthetic-ui-token", actor: { user_id: `${nextRole}-a`, role: nextRole },
    }));
    sessionStorage.setItem("task10.fixture-seeded", "yes");
  }, role);
}

async function contractApi(page: Page, options: { courseError?: number; detail?: string; delayedAcceptance?: boolean } = {}) {
  const calls: string[] = [];
  let accepts = 0;
  await page.route("**/*", async route => {
    const req = route.request();
    if (req.resourceType() !== "fetch") return route.continue();
    const path = new URL(req.url()).pathname;
    calls.push(path);
    const unavailable = { code: "RESOURCE_NOT_AVAILABLE", message: options.detail ?? "Resource is not available.", request_id: "req-ui-synthetic" };
    if (path === "/courses") return options.courseError
      ? route.fulfill({ status: options.courseError, json: unavailable })
      : route.fulfill({ json: [{ course_id: "course-a", title: "仓颉语言设计" }] });
    if (path === "/teacher/courses/course-a/analytics") return route.fulfill({ json: { status: "insufficient_sample", course_id: "course-a", filters, minimum_sample_size: 5 } });
    if (path === "/teacher/courses/course-a/review-queue") return route.fulfill({ json: { course_id: "course-a", filters, items: [] } });
    if (path === "/courses/course-a/exercises") return route.fulfill({ json: [] });
    if (path === "/me/memories") return route.fulfill({ json: [] });
    if (path === "/me/memory-proposals") return route.fulfill({ json: options.delayedAcceptance ? [{
      proposal_id: "ui-proposal", root_proposal_id: "ui-proposal", previous_proposal_id: null, version: 1,
      owner_user_id: "student-a", course_id: "course-a", diagnosis_id: "ui-diagnosis", explanation_check_id: "ui-check",
      content: "Synthetic proposal for repeated-click check", concept_ids: ["cj.pattern-match.exhaustiveness"], confidence: 0.9,
      status: "pending", created_at: "2026-10-07T01:00:00Z", expires_at: "2026-11-07T01:00:00Z", request_id: "req-ui-synthetic",
    }] : [] });
    if (path === "/memory-proposals/ui-proposal/accept") {
      accepts++;
      await new Promise(resolve => setTimeout(resolve, 250));
      return route.fulfill({ status: 503, json: { code: "STORAGE_UNAVAILABLE", message: "Synthetic delayed response", request_id: "req-ui-synthetic" } });
    }
    return route.fulfill({ status: 404, json: unavailable });
  });
  return { calls, accepts: () => accepts };
}

test("student entering a teacher URL never renders teacher controls", async ({ page }) => {
  await session(page, "student");
  const observed = await contractApi(page);
  await page.goto("/teacher/courses/course-a");
  await expect(page.getByRole("button", { name: "退出", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "课程诊断台" })).toHaveCount(0);
  expect(observed.calls.filter(p => p.startsWith("/teacher/"))).toEqual([]);
});

test("teacher entering a private memory URL never requests or displays private content", async ({ page }) => {
  await session(page, "teacher");
  const observed = await contractApi(page);
  await page.goto("/memories/private-student-memory");
  await expect(page.getByRole("heading", { name: "课程诊断台" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText(privateMarker);
  expect(observed.calls.filter(p => /memory-proposals|\/me\/memories|\/memories\//.test(p))).toEqual([]);
});

test("suppressed analytics shows no exact learner count or private conversation", async ({ page }) => {
  await session(page, "teacher");
  await contractApi(page);
  await page.goto("/");
  await expect(page.getByText("样本不足", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "匿名概念误区数据" })).toHaveCount(0);
  await expect(page.getByText("有效匿名样本", { exact: true })).toHaveCount(0);
  await expect(page.locator("main")).not.toContainText(privateMarker);
});

test("403 and 404 render the same public denial without server details", async ({ page }) => {
  await session(page, "teacher");
  for (const status of [403, 404]) {
    await page.unrouteAll();
    await contractApi(page, { courseError: status, detail: "Traceback SQLAlchemy password_hash PRIVATE_SERVER_DETAIL" });
    await page.goto(`/teacher/courses/${status === 403 ? "existing" : "unknown"}`);
    const alert = page.getByRole("alert").first();
    await expect(alert).toContainText("无法访问该资源");
    await expect(alert).not.toContainText("PRIVATE_SERVER_DETAIL");
    await expect(alert).not.toContainText("SQLAlchemy");
  }
});

test("error page hides sensitive service internals", async ({ page }) => {
  await session(page, "teacher");
  await contractApi(page, { courseError: 503, detail: "PRIVATE_SERVER_DETAIL postgres://credential Traceback" });
  await page.goto("/");
  const alert = page.getByRole("alert").first();
  await expect(alert).toContainText("服务暂不可用");
  await expect(alert).not.toContainText("PRIVATE_SERVER_DETAIL");
  await expect(alert).not.toContainText("credential");
});

test("logout clears persisted session and protected-page access", async ({ page }) => {
  await session(page, "teacher");
  await contractApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: "退出", exact: true }).click();
  expect(await page.evaluate(() => localStorage.getItem("knowbound.session"))).toBeNull();
  await page.goto("/teacher/courses/course-a");
  await expect(page.getByRole("heading", { name: "进入课程空间" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "课程诊断台" })).toHaveCount(0);
});

test("repeated acceptance clicks send one pending sensitive request", async ({ page }) => {
  await session(page, "student");
  const observed = await contractApi(page, { delayedAcceptance: true });
  await page.goto("/");
  const button = page.getByRole("button", { name: /^(接受记忆建议|正在保存…)$/ });
  await expect(button).toBeVisible();
  await button.evaluate((element: HTMLButtonElement) => { element.click(); element.click(); });
  await expect(button).toBeDisabled();
  await expect(page.getByRole("alert").first()).toBeVisible();
  expect(observed.accepts()).toBe(1);
});
