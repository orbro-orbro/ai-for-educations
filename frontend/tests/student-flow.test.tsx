import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/App";

const course = { course_id: "course-cj", title: "仓颉语言设计" };
const exercise = { exercise_id: "exercise-match", course_id: "course-cj", title: "补全 match 分支" };
const secondCourse = { course_id: "course-advanced", title: "仓颉进阶" };
const secondExercise = { exercise_id: "exercise-concurrency", course_id: "course-advanced", title: "并发练习" };

const submission = {
  submission_id: "submission-1",
  course_id: "course-cj",
  exercise_id: "exercise-match",
  owner_user_id: "student-1",
  source_files: [{ path: "main.cj", content: "main() {}" }],
  entrypoint: "main.cj",
  is_formal: true,
  status: "executed",
  created_at: "2026-10-07T01:00:00Z",
  request_id: "req-submit",
};

const executionResult = {
  submission_id: "submission-1",
  protocol_version: "2",
  status: "compile_failed",
  phase: "compile",
  retryable: false,
  exit_code: 1,
  signal: null,
  stdout: "",
  stderr: "Non-exhaustive patterns",
  stdout_truncated: false,
  stderr_truncated: false,
  diagnostics: [{ severity: "error", message: "match 分支未穷举", code: null, file: "main.cj", start_line: 2, start_column: 3, end_line: 2, end_column: 8 }],
  command_summary: { compiler: "cjc", source_count: 1, entrypoint: "main.cj", output_kind: "executable" },
  limits: { timeout_ms: 5000, max_output_chars: 65536, max_files: 32, max_source_bytes: 1048576, pids: 64, memory_bytes: 536870912, cpu_cores: 1 },
  toolchain: { cjc: "1.2.0", cjpm: "1.2.0", backend: "cjnative" },
  created_at: "2026-10-07T01:00:01Z",
  request_id: "req-execution",
  rule_matches: [],
};

const diagnosis = {
  diagnosis_id: "diagnosis-1",
  submission_id: "submission-1",
  course_id: "course-cj",
  owner_user_id: "student-1",
  category: "conceptual",
  locations: [{ file: "main.cj", start_line: 2, end_line: 2 }],
  concept_ids: ["cj.pattern-match.exhaustiveness"],
  root_cause: "没有覆盖枚举的全部可能值",
  evidence: [{ kind: "compiler_diagnostic", summary: "编译器报告 match 分支未穷举", diagnostic_index: 0 }],
  confidence: 0.92,
  recommended_hint_level: 1,
  requires_teacher_review: false,
  created_at: "2026-10-07T01:00:02Z",
  request_id: "req-diagnosis",
};

const proposal = {
  proposal_id: "proposal-1",
  root_proposal_id: "proposal-1",
  previous_proposal_id: null,
  version: 1,
  owner_user_id: "student-1",
  course_id: "course-cj",
  diagnosis_id: "diagnosis-1",
  explanation_check_id: "check-1",
  content: "我需要先检查 match 是否覆盖所有枚举分支。",
  concept_ids: ["cj.pattern-match.exhaustiveness"],
  confidence: 0.9,
  status: "pending",
  created_at: "2026-10-07T01:00:03Z",
  expires_at: "2026-11-07T01:00:03Z",
  request_id: "req-proposal",
};

const memory = {
  memory_id: "memory-1",
  logical_memory_id: "logical-1",
  previous_version_id: null,
  version: 1,
  owner_user_id: "student-1",
  course_id: "course-cj",
  memory_type: "misconception",
  visibility: "private",
  content: "我需要先检查 match 是否覆盖所有枚举分支。",
  concept_ids: ["cj.pattern-match.exhaustiveness"],
  source_diagnosis_id: "diagnosis-1",
  confidence: 0.9,
  allowed_purposes: ["learning_support"],
  status: "active",
  created_at: "2026-10-07T01:00:04Z",
  updated_at: "2026-10-07T01:00:04Z",
  expires_at: null,
  request_id: "req-memory",
};

type RouteHandler = (url: URL, init: RequestInit) => Response | Promise<Response> | undefined;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function useStudentApi(...overrides: RouteHandler[]) {
  localStorage.setItem(
    "knowbound.session",
    JSON.stringify({ accessToken: "student-token", actor: { user_id: "student-1", role: "student" } }),
  );

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    for (const override of overrides) {
      const result = await override(url, init);
      if (result) return result;
    }
    if (url.pathname === "/courses") return json([course]);
    if (url.pathname === "/courses/course-cj/exercises") return json([exercise]);
    if (url.pathname === "/me/memory-proposals") return json([]);
    if (url.pathname === "/me/memories") return json([]);
    if (url.pathname === "/submissions/submission-1" && (init.method ?? "GET") === "GET") return json(submission);
    throw new Error(`Unexpected request: ${init.method ?? "GET"} ${url.pathname}${url.search}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function submitCode() {
  const editor = await screen.findByLabelText("仓颉源码");
  fireEvent.change(editor, { target: { value: "main() { match (value) { case Some(v) => v } }" } });
  fireEvent.click(screen.getByRole("button", { name: "提交并运行" }));
}

describe("student learning loop", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("starts a new diagnosis after rejecting the previous memory suggestion", async () => {
    let submissions = 0;
    let rejected = false;
    const fetchMock = useStudentApi((url, init) => {
      if (url.pathname.endsWith("/submissions") && init.method === "POST") return json({ ...submission, submission_id: `submission-${++submissions}` }, 201);
      if (url.pathname === "/submissions/submission-2") return json({ ...submission, submission_id: "submission-2" });
      if (url.pathname.endsWith("/execution-result")) return json({ ...executionResult, submission_id: `submission-${submissions}` });
      if (url.pathname.endsWith("/diagnosis")) return json({ ...diagnosis, diagnosis_id: `diagnosis-${submissions}`, submission_id: `submission-${submissions}`, root_cause: submissions === 1 ? diagnosis.root_cause : "新一轮诊断" });
      if (url.pathname === "/me/memory-proposals") return json(rejected ? [] : [proposal]);
      if (url.pathname === "/memory-proposals/proposal-1/reject") {
        rejected = true;
        return json({ ...proposal, status: "rejected" });
      }
      if (url.pathname === "/diagnoses/diagnosis-1/attempts") return new Response(null, { status: 204 });
    });
    render(<App />);
    await submitCode();
    await screen.findByText(diagnosis.root_cause);
    fireEvent.click(await screen.findByRole("button", { name: "拒绝记忆建议" }));
    await screen.findByText("已拒绝这条记忆建议");
    await submitCode();
    await screen.findByText("新一轮诊断");
    expect(fetchMock.mock.calls.some(([url]) => new URL(String(url)).pathname.endsWith("/attempts"))).toBe(false);
    expect(screen.queryByText(proposal.content)).not.toBeInTheDocument();
  });

  it("associates a correction with the original diagnosis and retries linkage without resubmitting", async () => {
    let submissions = 0;
    let associations = 0;
    const fetchMock = useStudentApi((url, init) => {
      if (url.pathname.endsWith("/submissions") && init.method === "POST") return json({ ...submission, submission_id: `submission-${++submissions}` }, 201);
      if (url.pathname === "/submissions/submission-2") return json({ ...submission, submission_id: "submission-2" });
      if (url.pathname.endsWith("/execution-result")) return json({ ...executionResult, submission_id: `submission-${submissions}`, status: submissions === 2 ? "succeeded" : "compile_failed" });
      if (url.pathname.endsWith("/diagnosis")) return json(diagnosis);
      if (url.pathname === "/diagnoses/diagnosis-1/attempts") {
        expect(JSON.parse(String(init.body))).toEqual({ submission_id: "submission-2" });
        return ++associations === 1 ? json({ code: "STORAGE_UNAVAILABLE", message: "Synthetic unavailable", request_id: "association-failed" }, 503) : new Response(null, { status: 204 });
      }
    });
    render(<App />);
    await submitCode();
    await screen.findByText("没有覆盖枚举的全部可能值");
    await waitFor(() => expect(screen.getByRole("button", { name: "提交并运行" })).toBeEnabled());
    await submitCode();
    await screen.findByText(/association-failed/);
    expect(screen.queryByText("修复提交已关联原诊断")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试关联修复提交" }));
    await screen.findByText("修复提交已关联原诊断");
    expect(submissions).toBe(2);
    expect(associations).toBe(2);
    expect(fetchMock.mock.calls.filter(([url]) => new URL(String(url)).pathname.endsWith("/diagnosis"))).toHaveLength(1);
    expect(screen.getByText("没有覆盖枚举的全部可能值")).toBeInTheDocument();
  });

  it("submits Cangjie source through the selected exercise", async () => {
    const fetchMock = useStudentApi((url, init) => {
      if (url.pathname === "/exercises/exercise-match/submissions" && init.method === "POST") return json(submission, 201);
      if (url.pathname === "/submissions/submission-1/execution-result") return json(executionResult);
      if (url.pathname === "/submissions/submission-1/diagnosis") return json(diagnosis);
    });
    render(<App />);

    await submitCode();

    expect(await screen.findByText("真实编译反馈")).toBeInTheDocument();
    const submitCall = fetchMock.mock.calls.find(([url]) => String(url).includes("/exercises/exercise-match/submissions"));
    expect(JSON.parse(String(submitCall?.[1]?.body))).toMatchObject({ entrypoint: "main.cj", is_formal: true });
    expect(fetchMock.mock.calls.some(([url, init]) => new URL(String(url)).pathname === "/submissions/submission-1" && (init?.method ?? "GET") === "GET")).toBe(true);
  });

  it("shows execution unavailable without inventing compiler output", async () => {
    useStudentApi((url, init) => {
      if (url.pathname === "/exercises/exercise-match/submissions" && init.method === "POST") {
        return json({ ...submission, status: "execution_unavailable", request_id: "req-runner-down" }, 201);
      }
    });
    render(<App />);

    await submitCode();

    expect(await screen.findByText("执行服务暂不可用")).toBeInTheDocument();
    expect(screen.queryByText("编译成功")).not.toBeInTheDocument();
  });

  it("keeps real execution feedback when diagnosis fails and retries without resubmitting", async () => {
    let diagnosisAttempts = 0;
    const fetchMock = useStudentApi((url, init) => {
      if (url.pathname.endsWith("/submissions") && init.method === "POST") return json(submission, 201);
      if (url.pathname.endsWith("/execution-result")) return json(executionResult);
      if (url.pathname.endsWith("/diagnosis")) {
        diagnosisAttempts += 1;
        return diagnosisAttempts === 1 ? json({ code: "DIAGNOSIS_UNAVAILABLE", message: "temporarily unavailable", request_id: "req-diagnosis-fail" }, 503) : json(diagnosis);
      }
    });
    render(<App />);
    await submitCode();

    expect(await screen.findByText("真实编译反馈")).toBeInTheDocument();
    expect(screen.getByText("match 分支未穷举")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新读取诊断" }));
    expect(await screen.findByText("没有覆盖枚举的全部可能值")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => new URL(String(url)).pathname === "/exercises/exercise-match/submissions")).toHaveLength(1);
  });

  it("distinguishes runtime failure and preserves stderr", async () => {
    useStudentApi((url, init) => {
      if (url.pathname.endsWith("/submissions") && init.method === "POST") return json(submission, 201);
      if (url.pathname.endsWith("/execution-result")) return json({ ...executionResult, status: "run_failed", phase: "run", diagnostics: [], stdout: "partial output", stderr: "panic: index out of bounds" });
      if (url.pathname.endsWith("/diagnosis")) return json(diagnosis);
    });
    render(<App />);
    await submitCode();

    expect(await screen.findByText("运行失败")).toBeInTheDocument();
    expect(screen.getByText(/panic: index out of bounds/)).toBeInTheDocument();
    expect(screen.queryByText("编译未通过")).not.toBeInTheDocument();
  });

  it("ignores a stale exercise response after the course changes again", async () => {
    let resolveAdvanced!: (value: Response) => void;
    const delayedAdvanced = new Promise<Response>((resolve) => { resolveAdvanced = resolve; });
    useStudentApi((url) => {
      if (url.pathname === "/courses") return json([course, secondCourse]);
      if (url.pathname === "/courses/course-advanced/exercises") return delayedAdvanced;
      if (url.pathname === "/courses/course-cj/exercises") return json([exercise]);
    });
    render(<App />);
    const courseSelect = await screen.findByLabelText("课程");
    fireEvent.change(courseSelect, { target: { value: secondCourse.course_id } });
    fireEvent.change(courseSelect, { target: { value: course.course_id } });
    resolveAdvanced(json([secondExercise]));

    await waitFor(() => expect(screen.getByRole("option", { name: exercise.title })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: secondExercise.title })).not.toBeInTheDocument();
  });

  it("renders an evidence-bound misconception diagnosis", async () => {
    useStudentApi((url, init) => {
      if (url.pathname.endsWith("/submissions") && init.method === "POST") return json(submission, 201);
      if (url.pathname.endsWith("/execution-result")) return json(executionResult);
      if (url.pathname.endsWith("/diagnosis")) return json(diagnosis);
    });
    render(<App />);

    await submitCode();

    expect(await screen.findByText("没有覆盖枚举的全部可能值")).toBeInTheDocument();
    expect(screen.getByText("编译器报告 match 分支未穷举")).toBeInTheDocument();
  });

  it("marks a low-confidence diagnosis as waiting for teacher review", async () => {
    useStudentApi((url, init) => {
      if (url.pathname.endsWith("/submissions") && init.method === "POST") return json(submission, 201);
      if (url.pathname.endsWith("/execution-result")) return json(executionResult);
      if (url.pathname.endsWith("/diagnosis")) return json({ ...diagnosis, confidence: 0.42, requires_teacher_review: true });
    });
    render(<App />);

    await submitCode();

    expect(await screen.findByText("等待教师复核")).toBeInTheDocument();
    expect(screen.getByText(/不会写入长期记忆/)).toBeInTheDocument();
  });

  it("requests the next hint level and displays its safe content", async () => {
    useStudentApi((url, init) => {
      if (url.pathname.endsWith("/submissions") && init.method === "POST") return json(submission, 201);
      if (url.pathname.endsWith("/execution-result")) return json(executionResult);
      if (url.pathname.endsWith("/diagnosis")) return json(diagnosis);
      if (url.pathname.endsWith("/hints/next") && init.method === "POST") {
        return json({ hint_event_id: "hint-1", diagnosis_id: "diagnosis-1", previous_level: 1, current_level: 2, reason: "still-stuck", previous_attempt_count: 1, content: "回顾枚举的所有构造器。", used_safe_fallback: false, created_at: "2026-10-07T01:01:00Z", request_id: "req-hint" });
      }
    });
    render(<App />);
    await submitCode();
    fireEvent.click(await screen.findByRole("button", { name: "请求下一层提示" }));

    expect(await screen.findByText("第 2 级提示")).toBeInTheDocument();
    expect(screen.getByText("回顾枚举的所有构造器。")).toBeInTheDocument();
  });

  it("checks the student's explanation and reports memory eligibility", async () => {
    useStudentApi((url, init) => {
      if (url.pathname.endsWith("/submissions") && init.method === "POST") return json(submission, 201);
      if (url.pathname.endsWith("/execution-result")) return json(executionResult);
      if (url.pathname.endsWith("/diagnosis")) return json(diagnosis);
      if (url.pathname.endsWith("/explanation-check") && init.method === "POST") {
        return json({ explanation_check_id: "check-1", diagnosis_id: "diagnosis-1", understands: true, concept_ids: diagnosis.concept_ids, evidence_summary: "解释提到了穷举要求", confidence: 0.91, feedback: "你已经抓住了根因。", memory_proposal_eligible: true, created_at: "2026-10-07T01:02:00Z", request_id: "req-check" });
      }
    });
    render(<App />);
    await submitCode();
    fireEvent.change(await screen.findByLabelText("我对错误原因的解释"), { target: { value: "match 必须覆盖枚举的所有构造器。" } });
    fireEvent.click(screen.getByRole("button", { name: "验证我的理解" }));

    expect(await screen.findByText("你已经抓住了根因。")).toBeInTheDocument();
    expect(screen.getByText("可以生成记忆建议")).toBeInTheDocument();
  });

  it("accepts a pending memory proposal only after the student acts", async () => {
    useStudentApi(
      (url) => url.pathname === "/me/memory-proposals" ? json([proposal]) : undefined,
      (url, init) => url.pathname === "/memory-proposals/proposal-1/accept" && init.method === "POST" ? json(memory) : undefined,
    );
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "接受记忆建议" }));

    expect(await screen.findByText("已保存到个人记忆")).toBeInTheDocument();
  });

  it("locks a memory proposal while acceptance is in flight", async () => {
    let resolveAccept!: (value: Response) => void;
    const pendingAccept = new Promise<Response>((resolve) => { resolveAccept = resolve; });
    const fetchMock = useStudentApi(
      (url) => url.pathname === "/me/memory-proposals" ? json([proposal]) : undefined,
      (url, init) => url.pathname === "/memory-proposals/proposal-1/accept" && init.method === "POST" ? pendingAccept : undefined,
    );
    render(<App />);
    const acceptButton = await screen.findByRole("button", { name: "接受记忆建议" });
    fireEvent.click(acceptButton);
    fireEvent.click(acceptButton);

    expect(acceptButton).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/memory-proposals/proposal-1/accept"))).toHaveLength(1);
    resolveAccept(json(memory));
    expect(await screen.findByText("已保存到个人记忆")).toBeInTheDocument();
  });

  it("rejects a pending memory proposal without creating a memory", async () => {
    useStudentApi(
      (url) => url.pathname === "/me/memory-proposals" ? json([proposal]) : undefined,
      (url, init) => url.pathname === "/memory-proposals/proposal-1/reject" && init.method === "POST" ? json({ ...proposal, status: "rejected" }) : undefined,
    );
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "拒绝记忆建议" }));

    expect(await screen.findByText("已拒绝这条记忆建议")).toBeInTheDocument();
  });

  it("requires explicit confirmation before deleting a private memory", async () => {
    const fetchMock = useStudentApi((url) => url.pathname === "/me/memories" ? json([memory]) : undefined);
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "删除记忆" }));

    expect(screen.getByRole("dialog", { name: "确认删除个人记忆" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认删除" })).toHaveFocus();
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes("/memories/memory-1") && init?.method === "DELETE")).toBe(false);
  });

  it("keeps deletion-pending memories visibly non-retrievable", async () => {
    useStudentApi(
      (url) => url.pathname === "/me/memories" ? json([memory]) : undefined,
      (url, init) => url.pathname === "/memories/memory-1" && init.method === "DELETE" ? json({ deletion_id: "deletion-1", memory_id: "memory-1", owner_user_id: "student-1", course_id: "course-cj", status: "deletion_pending", requested_at: "2026-10-07T01:03:00Z", completed_at: null, attempts: 1, index_cleared: false, cache_cleared: false, model_references_cleared: false, reverse_lookup_absent: false, error_code: null, request_id: "req-delete" }, 202) : undefined,
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "删除记忆" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await screen.findByText("删除处理中")).toBeInTheDocument();
    expect(screen.getByText(/已经停止用于学习支持/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "刷新删除状态" })).toBeInTheDocument();
  });

  it("removes all correction and deletion controls after deletion completes", async () => {
    useStudentApi(
      (url) => url.pathname === "/me/memories" ? json([memory]) : undefined,
      (url, init) => url.pathname === "/memories/memory-1" && init.method === "DELETE" ? json({ deletion_id: "deletion-1", memory_id: "memory-1", owner_user_id: "student-1", course_id: "course-cj", status: "deleted", requested_at: "2026-10-07T01:03:00Z", completed_at: "2026-10-07T01:03:01Z", attempts: 1, index_cleared: true, cache_cleared: true, model_references_cleared: true, reverse_lookup_absent: true, error_code: null, request_id: "req-delete" }) : undefined,
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "删除记忆" }));
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));

    expect(await screen.findByText("记忆已删除")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "纠正记忆" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除记忆" })).not.toBeInTheDocument();
  });

  it("shows a recoverable API error with its request ID and retry action", async () => {
    let attempts = 0;
    useStudentApi((url) => {
      if (url.pathname !== "/courses") return undefined;
      attempts += 1;
      return attempts === 1
        ? json({ code: "SERVICE_UNAVAILABLE", message: "temporarily unavailable", request_id: "req-course-fail" }, 503)
        : json([course]);
    });
    render(<App />);

    expect(await screen.findByText("请求编号：req-course-fail")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试加载课程" }));

    expect(await screen.findByText("补全 match 分支")).toBeInTheDocument();
  });

  it("uses a non-enumerating denied-access state", async () => {
    useStudentApi((url) => url.pathname === "/courses" ? json({ code: "RESOURCE_NOT_AVAILABLE", message: "not available", request_id: "req-denied" }, 404) : undefined);
    render(<App />);

    expect(await screen.findByText("无法访问该资源")).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-denied")).toBeInTheDocument();
    expect(screen.queryByText("资源不存在")).not.toBeInTheDocument();
  });
});
