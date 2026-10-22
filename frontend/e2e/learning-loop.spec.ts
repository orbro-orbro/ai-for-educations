import { expect, test, type Page, type Request } from "@playwright/test";

const course = { course_id: "course-cj", title: "仓颉语言设计" };
const exercise = { exercise_id: "exercise-match", course_id: "course-cj", title: "补全 match 分支" };
const filters = { concept_id: null, exercise_id: null, start_at: null, end_at: null };

for (const viewport of [
  { width: 1366, height: 768 }, { width: 1920, height: 1080 },
  { width: 2560, height: 1440 }, { width: 1280, height: 720 },
  { width: 390, height: 844 }, { width: 360, height: 640 },
  { width: 640, height: 360 },
]) {
  test(`login layout keeps introduction and form aligned at ${viewport.width}x${viewport.height}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "进入课程空间" })).toBeVisible();
    const intro = (await page.locator(".login-intro").boundingBox())!;
    const panel = (await page.locator(".login-panel").boundingBox())!;
    const heading = (await page.getByRole("heading", { name: "知界·仓颉学伴" }).boundingBox())!;
    const login = page.getByRole("button", { name: "登录", exact: true });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (viewport.width > 720) {
      expect(Math.abs(intro.y - panel.y)).toBeLessThanOrEqual(1);
      expect(intro.x).toBe(0);
      expect(panel.x).toBeGreaterThanOrEqual(intro.x + intro.width - 1);
      const button = (await login.boundingBox())!;
      expect(button.y + button.height).toBeLessThanOrEqual(viewport.height);
    } else {
      expect(intro.x).toBe(0);
      expect(panel.x).toBe(0);
      expect(panel.y).toBeGreaterThanOrEqual(intro.y + intro.height - 1);
    }
    expect(heading.y).toBeGreaterThanOrEqual(intro.y);
    expect(heading.y + heading.height).toBeLessThanOrEqual(intro.y + intro.height);
    const note = page.getByRole("note");
    await expect(note).toHaveCount(process.env.VITE_SYNTHETIC_DEMO === "true" ? 1 : 0);
    if (process.env.VITE_SYNTHETIC_DEMO === "true") {
      await expect(note).toContainText("非教学试点结果");
      const banner = (await note.boundingBox())!;
      expect(banner.x).toBe(0);
      expect(Math.abs(banner.width - viewport.width)).toBeLessThanOrEqual(1);
      expect(banner.height).toBeLessThan(viewport.height / 4);
      expect(intro.y).toBeGreaterThanOrEqual(banner.y + banner.height - 1);
    }
    await page.getByLabel("用户名").fill("synthetic-layout-user");
    await page.getByLabel("密码").fill("synthetic-layout-password");
    await page.getByLabel("用户名").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("密码")).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(login).toBeFocused();
    await expect(login).toBeEnabled();
    await expect(login).toBeInViewport();
  });
}

async function installSession(page: Page, role: "student" | "teacher") {
  await page.addInitScript((nextRole) => localStorage.setItem("knowbound.session", JSON.stringify({ accessToken: `${nextRole}-token`, actor: { user_id: `${nextRole}-1`, role: nextRole } })), role);
}

async function mockStudentApi(page: Page) {
  let proposalAvailable = true;
  const savedMemory = { memory_id: "memory-1", logical_memory_id: "logical-1", previous_version_id: null, version: 1, owner_user_id: "student-1", course_id: "course-cj", memory_type: "misconception", visibility: "private", content: "我需要先检查 match 是否覆盖所有枚举分支。", concept_ids: ["cj.pattern-match.exhaustiveness"], source_diagnosis_id: "diagnosis-1", confidence: .9, allowed_purposes: ["learning_support"], status: "active", created_at: "2026-10-07T01:00:04Z", updated_at: "2026-10-07T01:00:04Z", expires_at: null, request_id: "req-memory" };
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.resourceType() !== "fetch") return route.continue();
    if (url.pathname === "/courses") return route.fulfill({ json: [course] });
    if (url.pathname === "/courses/course-cj/exercises") return route.fulfill({ json: [exercise] });
    if (url.pathname === "/me/memory-proposals") return route.fulfill({ json: proposalAvailable ? [{ proposal_id: "proposal-1", root_proposal_id: "proposal-1", previous_proposal_id: null, version: 1, owner_user_id: "student-1", course_id: "course-cj", diagnosis_id: "diagnosis-1", explanation_check_id: "check-1", content: "我需要先检查 match 是否覆盖所有枚举分支。", concept_ids: ["cj.pattern-match.exhaustiveness"], confidence: .9, status: "pending", created_at: "2026-10-07T01:00:00Z", expires_at: "2026-11-07T01:00:00Z", request_id: "req-proposal" }] : [] });
    if (url.pathname === "/me/memories") return route.fulfill({ json: [] });
    if (url.pathname === "/exercises/exercise-match/submissions" && request.method() === "POST") return route.fulfill({ status: 201, json: { submission_id: "submission-1", course_id: "course-cj", exercise_id: "exercise-match", owner_user_id: "student-1", source_files: [{ path: "main.cj", content: "main() {}" }], entrypoint: "main.cj", is_formal: true, status: "executed", created_at: "2026-10-07T01:00:00Z", request_id: "req-submit" } });
    if (url.pathname === "/submissions/submission-1") return route.fulfill({ json: { submission_id: "submission-1", course_id: "course-cj", exercise_id: "exercise-match", owner_user_id: "student-1", source_files: [{ path: "main.cj", content: "main() {}" }], entrypoint: "main.cj", is_formal: true, status: "executed", created_at: "2026-10-07T01:00:00Z", request_id: "req-submit-status" } });
    if (url.pathname === "/submissions/submission-1/execution-result") return route.fulfill({ json: { submission_id: "submission-1", protocol_version: "2", status: "compile_failed", phase: "compile", retryable: false, exit_code: 1, signal: null, stdout: "", stderr: "Non-exhaustive patterns", stdout_truncated: false, stderr_truncated: false, diagnostics: [{ severity: "error", message: "match 分支未穷举", code: null, file: "main.cj", start_line: 2, start_column: 3, end_line: 2, end_column: 8 }], command_summary: { compiler: "cjc", source_count: 1, entrypoint: "main.cj", output_kind: "executable" }, limits: { timeout_ms: 5000, max_output_chars: 65536, max_files: 32, max_source_bytes: 1048576, pids: 64, memory_bytes: 536870912, cpu_cores: 1 }, toolchain: { cjc: "1.2.0", cjpm: "1.2.0", backend: "cjnative" }, created_at: "2026-10-07T01:00:01Z", request_id: "req-execution", rule_matches: [] } });
    if (url.pathname === "/submissions/submission-1/diagnosis") return route.fulfill({ json: { diagnosis_id: "diagnosis-1", submission_id: "submission-1", course_id: "course-cj", owner_user_id: "student-1", category: "conceptual", locations: [{ file: "main.cj", start_line: 2, end_line: 2 }], concept_ids: ["cj.pattern-match.exhaustiveness"], root_cause: "没有覆盖枚举的全部可能值", evidence: [{ kind: "compiler_diagnostic", summary: "编译器报告 match 分支未穷举", diagnostic_index: 0 }], confidence: .92, recommended_hint_level: 1, requires_teacher_review: false, created_at: "2026-10-07T01:00:02Z", request_id: "req-diagnosis" } });
    if (url.pathname === "/diagnoses/diagnosis-1/hints/next") return route.fulfill({ json: { hint_event_id: "hint-1", diagnosis_id: "diagnosis-1", previous_level: 1, current_level: 2, reason: "student-requested-more-guidance", previous_attempt_count: 1, content: "回顾枚举的所有构造器。", used_safe_fallback: false, created_at: "2026-10-07T01:01:00Z", request_id: "req-hint" } });
    if (url.pathname === "/diagnoses/diagnosis-1/explanation-check") return route.fulfill({ json: { explanation_check_id: "check-1", diagnosis_id: "diagnosis-1", understands: true, concept_ids: ["cj.pattern-match.exhaustiveness"], evidence_summary: "解释提到了穷举要求", confidence: .91, feedback: "你已经抓住了根因。", memory_proposal_eligible: true, created_at: "2026-10-07T01:02:00Z", request_id: "req-check" } });
    if (url.pathname === "/memory-proposals/proposal-1/accept") { proposalAvailable = false; return route.fulfill({ json: savedMemory }); }
    if (url.pathname === "/memories/memory-1" && request.method() === "PATCH") return route.fulfill({ json: { ...savedMemory, version: 2, content: "我会逐项检查 match 的枚举构造器。", request_id: "req-correct" } });
    if (url.pathname === "/memories/memory-1" && request.method() === "DELETE") return route.fulfill({ status: 202, json: { deletion_id: "deletion-1", memory_id: "memory-1", owner_user_id: "student-1", course_id: "course-cj", status: "deletion_pending", requested_at: "2026-10-07T01:03:00Z", completed_at: null, attempts: 1, index_cleared: false, cache_cleared: false, model_references_cleared: false, reverse_lookup_absent: false, error_code: null, request_id: "req-delete" } });
    if (url.pathname === "/memory-deletions/deletion-1") return route.fulfill({ json: { deletion_id: "deletion-1", memory_id: "memory-1", owner_user_id: "student-1", course_id: "course-cj", status: "deleted", requested_at: "2026-10-07T01:03:00Z", completed_at: "2026-10-07T01:04:00Z", attempts: 2, index_cleared: true, cache_cleared: true, model_references_cleared: true, reverse_lookup_absent: true, error_code: null, request_id: "req-delete-done" } });
    return route.fulfill({ status: 404, json: { code: "NOT_FOUND", message: "not mocked", request_id: "req-mock" } });
  });
}

async function mockTeacherApi(page: Page, requests: Request[]) {
  page.on("request", (request) => { if (request.resourceType() === "fetch") requests.push(request); });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.resourceType() !== "fetch") return route.continue();
    if (url.pathname === "/courses") return route.fulfill({ json: [course] });
    if (url.pathname === "/teacher/courses/course-cj/analytics") return route.fulfill({ json: { status: "available", course_id: "course-cj", filters, minimum_sample_size: 5, sample_size: 12, groups: [{ concept_id: "cj.pattern-match.exhaustiveness", exercise_id: "exercise-match", category: "conceptual", sample_size: 8, diagnosis_count: 11, independent_repair_count: 6 }] } });
    if (url.pathname === "/teacher/courses/course-cj/review-queue") return route.fulfill({ json: { course_id: "course-cj", filters, items: [{ queue_event_id: "queue-1", diagnosis_id: "diagnosis-1", submission_id: "submission-1", exercise_id: "exercise-match", category: "conceptual", concept_ids: ["cj.pattern-match.exhaustiveness"], root_cause: "match 分支可能未穷举", evidence_summaries: ["编译器报告非穷举分支"], confidence: .42, review_reason: "置信度低于课程阈值", queued_at: "2026-10-07T01:00:00Z" }] } });
    return route.fulfill({ status: 404, json: { code: "NOT_FOUND", message: "not mocked", request_id: "req-mock" } });
  });
}

test("student completes the evidence, understanding, and memory path on desktop", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await installSession(page, "student");
  await mockStudentApi(page);
  await page.goto("/");
  await page.getByLabel("仓颉源码").fill("main() { match (value) { case Some(v) => v } }");
  await page.getByRole("button", { name: "提交并运行" }).click();
  await expect(page.getByRole("heading", { name: "真实编译反馈" })).toBeVisible();
  await expect(page.getByText("没有覆盖枚举的全部可能值")).toBeVisible();
  await expect(page.getByText("概念理解", { exact: true })).toBeVisible();
  await expect(page.getByText("编译器诊断", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "请求下一层提示" }).click();
  await expect(page.getByText("回顾枚举的所有构造器。")).toBeVisible();
  await page.getByLabel("我对错误原因的解释").fill("match 必须覆盖枚举的所有构造器。");
  await page.getByRole("button", { name: "验证我的理解" }).click();
  await expect(page.getByText("你已经抓住了根因。")).toBeVisible();
  await page.getByRole("button", { name: "接受记忆建议" }).click();
  await expect(page.getByText("已保存到个人记忆")).toBeVisible();
  await page.getByRole("button", { name: "纠正记忆" }).click();
  await page.getByLabel("纠正后的记忆").fill("我会逐项检查 match 的枚举构造器。");
  await page.getByRole("button", { name: "保存纠正" }).click();
  await expect(page.getByText("记忆已按你的表述更新")).toBeVisible();
  await page.getByRole("button", { name: "删除记忆" }).click();
  await expect(page.getByRole("button", { name: "确认删除" })).toBeFocused();
  await page.getByRole("button", { name: "确认删除" }).click();
  await expect(page.getByText("删除处理中")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: "test-results/student-desktop.png", fullPage: true });
  await page.getByRole("button", { name: "刷新删除状态" }).click();
  await expect(page.getByText("记忆已删除")).toBeVisible();
});

test("missing diagnosis preserves execution feedback and rechecks access on reread", async ({ page }) => {
  await installSession(page, "student");
  await mockStudentApi(page);
  let revoked = false;
  let submissions = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/submissions")) submissions++;
  });
  await page.route("**/submissions/submission-1", (route) => route.fulfill(revoked ? {
    status: 404, json: { code: "RESOURCE_NOT_AVAILABLE", message: "Unavailable", request_id: "browser-revoked" },
  } : {
    json: { submission_id: "submission-1", course_id: "course-cj", exercise_id: "exercise-match", owner_user_id: "student-1", source_files: [{ path: "main.cj", content: "main() {}" }], entrypoint: "main.cj", is_formal: true, status: "needs_review", created_at: "2026-10-07T01:00:00Z", request_id: "req-submit-status" },
  }));
  await page.route("**/submissions/submission-1/diagnosis", (route) => route.fulfill({
    status: 404, json: { code: "RESOURCE_NOT_AVAILABLE", message: "Unavailable", request_id: "browser-no-diagnosis" },
  }));
  await page.goto("/");
  await page.getByRole("button", { name: "提交并运行" }).click();
  await expect(page.getByText("诊断暂不可用", { exact: true })).toBeVisible();
  await expect(page.getByText("真实编译反馈", { exact: true })).toBeVisible();
  await expect(page.getByText("match 分支未穷举", { exact: true })).toBeVisible();
  await expect(page.getByText(/browser-no-diagnosis/)).toBeVisible();
  await expect(page.getByText("无法访问该资源", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "重新读取诊断" }).click();
  await expect(page.getByText("诊断暂不可用", { exact: true })).toBeVisible();
  revoked = true;
  await page.getByRole("button", { name: "重新读取诊断" }).click();
  await expect(page.getByText("无法访问该资源", { exact: true })).toBeVisible();
  await expect(page.getByText(/browser-revoked/)).toBeVisible();
  await expect(page.getByText("诊断暂不可用", { exact: true })).toHaveCount(0);
  expect(submissions).toBe(1);
});

test("teacher sees only anonymous signals on a phone viewport", async ({ page }) => {
  const requests: Request[] = [];
  await page.setViewportSize({ width: 390, height: 844 });
  await installSession(page, "teacher");
  await mockTeacherApi(page, requests);
  await page.goto("/");
  await expect(page.getByRole("table", { name: "匿名概念误区数据" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "类型 概念理解", exact: true })).toBeVisible();
  await expect(page.getByText("match 分支可能未穷举")).toBeVisible();
  expect(requests.some((request) => /memory-proposals|\/me\/memories|\/memories\//.test(request.url()))).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  expect(await page.locator(".table-scroll").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.screenshot({ path: "test-results/teacher-mobile.png", fullPage: true });
});
