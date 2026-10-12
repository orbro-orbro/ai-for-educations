import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "../src/App";

const course = { course_id: "course-cj", title: "仓颉语言设计" };
const filters = { concept_id: null, exercise_id: null, start_at: null, end_at: null };
const analytics = {
  status: "available",
  course_id: "course-cj",
  filters,
  minimum_sample_size: 5,
  sample_size: 12,
  groups: [{ concept_id: "cj.pattern-match.exhaustiveness", exercise_id: "exercise-match", category: "conceptual", sample_size: 8, diagnosis_count: 11, independent_repair_count: 6 }],
};
const queueItem = {
  queue_event_id: "queue-1",
  diagnosis_id: "diagnosis-1",
  submission_id: "submission-1",
  exercise_id: "exercise-match",
  category: "conceptual",
  concept_ids: ["cj.pattern-match.exhaustiveness"],
  root_cause: "match 分支可能未穷举",
  evidence_summaries: ["编译器报告非穷举分支"],
  confidence: 0.42,
  review_reason: "置信度低于课程阈值",
  queued_at: "2026-10-07T01:00:00Z",
};

type RouteHandler = (url: URL, init: RequestInit) => Response | Promise<Response> | undefined;

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function useTeacherApi(...overrides: RouteHandler[]) {
  localStorage.setItem(
    "knowbound.session",
    JSON.stringify({ accessToken: "teacher-token", actor: { user_id: "teacher-1", role: "teacher" } }),
  );
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    for (const override of overrides) {
      const result = await override(url, init);
      if (result) return result;
    }
    if (url.pathname === "/courses") return json([course]);
    if (url.pathname === "/teacher/courses/course-cj/analytics") return json(analytics);
    if (url.pathname === "/teacher/courses/course-cj/review-queue") return json({ course_id: "course-cj", filters, items: [] });
    throw new Error(`Unexpected request: ${init.method ?? "GET"} ${url.pathname}${url.search}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("teacher privacy dashboard", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("renders anonymous aggregate groups with a tabular alternative", async () => {
    useTeacherApi();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "匿名概念误区分析" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "cj.pattern-match.exhaustiveness" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "匿名概念误区数据" })).toBeInTheDocument();
  });

  it("renders privacy suppression without an exact sample count", async () => {
    useTeacherApi((url) => url.pathname.endsWith("/analytics") ? json({ status: "insufficient_sample", course_id: "course-cj", filters, minimum_sample_size: 5 }) : undefined);
    render(<App />);

    expect(await screen.findByText("样本不足")).toBeInTheDocument();
    expect(screen.queryByText(/当前样本.*[0-9]/)).not.toBeInTheDocument();
  });

  it("never exposes or requests student private memories", async () => {
    const fetchMock = useTeacherApi();
    render(<App />);
    await screen.findByRole("heading", { name: "匿名概念误区分析" });

    expect(screen.queryByText("学生私人记忆")).not.toBeInTheDocument();
    expect(screen.queryByText("私人对话")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => /memory-proposals|\/me\/memories|\/memories\//.test(String(url)))).toBe(false);
  });

  it("shows de-identified diagnoses waiting for review", async () => {
    useTeacherApi((url) => url.pathname.endsWith("/review-queue") ? json({ course_id: "course-cj", filters, items: [queueItem] }) : undefined);
    render(<App />);

    expect(await screen.findByText("match 分支可能未穷举")).toBeInTheDocument();
    expect(screen.getByText("编译器报告非穷举分支")).toBeInTheDocument();
    expect(screen.queryByText(/student-1|owner_user_id/)).not.toBeInTheDocument();
  });

  it("submits a review decision and reason", async () => {
    useTeacherApi(
      (url) => url.pathname.endsWith("/review-queue") ? json({ course_id: "course-cj", filters, items: [queueItem] }) : undefined,
      (url, init) => url.pathname === "/teacher/diagnoses/diagnosis-1/review" && init.method === "POST" ? json({ diagnosis_id: "diagnosis-1", course_id: "course-cj", reviewer_user_id: "teacher-1", decision: "confirmed", reason: "证据与课程概念一致", reviewed_at: "2026-10-07T01:05:00Z" }) : undefined,
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("复核决定"), { target: { value: "confirmed" } });
    fireEvent.change(screen.getByLabelText("复核理由"), { target: { value: "证据与课程概念一致" } });
    fireEvent.click(screen.getByRole("button", { name: "提交复核" }));

    expect(await screen.findByText("已处理")).toBeInTheDocument();
  });

  it("keeps each review form independent and locks the submitted row", async () => {
    const secondItem = { ...queueItem, queue_event_id: "queue-2", diagnosis_id: "diagnosis-2", submission_id: "submission-2", root_cause: "所有权移动路径需要复核" };
    let resolveReview!: (value: Response) => void;
    const pendingReview = new Promise<Response>((resolve) => { resolveReview = resolve; });
    const fetchMock = useTeacherApi(
      (url) => url.pathname.endsWith("/review-queue") ? json({ course_id: "course-cj", filters, items: [queueItem, secondItem] }) : undefined,
      (url, init) => url.pathname === "/teacher/diagnoses/diagnosis-1/review" && init.method === "POST" ? pendingReview : undefined,
    );
    render(<App />);
    const reasons = await screen.findAllByLabelText("复核理由");
    fireEvent.change(reasons[0], { target: { value: "第一条诊断的独立理由" } });

    expect(reasons[1]).toHaveValue("");
    const submitButtons = screen.getAllByRole("button", { name: "提交复核" });
    fireEvent.click(submitButtons[0]);
    fireEvent.click(submitButtons[0]);
    expect(submitButtons[0]).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/teacher/diagnoses/diagnosis-1/review"))).toHaveLength(1);
    resolveReview(json({ diagnosis_id: "diagnosis-1", course_id: "course-cj", reviewer_user_id: "teacher-1", decision: "confirmed", reason: "第一条诊断的独立理由", reviewed_at: "2026-10-07T01:05:00Z" }));
    expect(await screen.findByText("已处理")).toBeInTheDocument();
  });

  it("sends date-time filters and renders a privacy-safe adjacent-window trend", async () => {
    const fetchMock = useTeacherApi();
    render(<App />);
    await screen.findByRole("heading", { name: "匿名概念误区分析" });
    fireEvent.change(screen.getByLabelText("开始日期"), { target: { value: "2026-09-01" } });
    fireEvent.change(screen.getByLabelText("结束日期"), { target: { value: "2026-09-30" } });
    fireEvent.click(screen.getByRole("button", { name: "应用筛选" }));

    expect(await screen.findByRole("heading", { name: "相邻时间窗口趋势" })).toBeInTheDocument();
    await waitFor(() => {
      const filteredCalls = fetchMock.mock.calls.map(([input]) => new URL(String(input))).filter((url) => url.pathname.endsWith("/analytics") && url.searchParams.has("start_at"));
      expect(filteredCalls.length).toBeGreaterThanOrEqual(2);
      expect(filteredCalls.every((url) => url.searchParams.get("start_at")?.includes("T") && url.searchParams.get("end_at")?.includes("T"))).toBe(true);
    });
  });

  it("treats a 409 review replay as an idempotent conflict", async () => {
    useTeacherApi(
      (url) => url.pathname.endsWith("/review-queue") ? json({ course_id: "course-cj", filters, items: [queueItem] }) : undefined,
      (url, init) => url.pathname.endsWith("/review") && init.method === "POST" ? json({ code: "REVIEW_CONFLICT", message: "already reviewed", request_id: "req-review-conflict" }, 409) : undefined,
    );
    render(<App />);
    fireEvent.change(await screen.findByLabelText("复核理由"), { target: { value: "证据不足，需要确认" } });
    fireEvent.click(screen.getByRole("button", { name: "提交复核" }));

    expect(await screen.findByText("该诊断已被处理，请刷新队列")).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-review-conflict")).toBeInTheDocument();
  });

  it("uses the same non-enumerating state for denied teacher resources", async () => {
    useTeacherApi((url) => url.pathname.endsWith("/analytics") ? json({ code: "RESOURCE_NOT_AVAILABLE", message: "not available", request_id: "req-teacher-denied" }, 404) : undefined);
    render(<App />);

    expect(await screen.findByText("无法访问该课程资源")).toBeInTheDocument();
    expect(screen.getByText("请求编号：req-teacher-denied")).toBeInTheDocument();
  });

  it("renders an empty review queue as an actionable state", async () => {
    useTeacherApi();
    render(<App />);

    expect(await screen.findByText("当前没有待复核诊断")).toBeInTheDocument();
  });

  it("recovers from a review queue loading failure", async () => {
    let attempts = 0;
    useTeacherApi((url) => {
      if (!url.pathname.endsWith("/review-queue")) return undefined;
      attempts += 1;
      return attempts === 1
        ? json({ code: "SERVICE_UNAVAILABLE", message: "temporarily unavailable", request_id: "req-queue-fail" }, 503)
        : json({ course_id: "course-cj", filters, items: [] });
    });
    render(<App />);

    expect(await screen.findByText("请求编号：req-queue-fail")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试复核队列" }));

    await waitFor(() => expect(screen.getByText("当前没有待复核诊断")).toBeInTheDocument());
  });
});
