export type Role = "student" | "teacher";

export interface Actor { user_id: string; role: Role }
export interface SessionData { accessToken: string; actor: Actor }
export interface LoginResponse { access_token: string; token_type: "bearer"; actor: Actor }
export interface CourseSummary { course_id: string; title: string }
export interface ExerciseSummary { exercise_id: string; course_id: string; title: string }
export interface SourceFileInput { path: string; content: string }
export type SubmissionStatus = "received" | "executing" | "executed" | "execution_unavailable" | "diagnosing" | "diagnosed" | "needs_review";
export interface Submission {
  submission_id: string; course_id: string; exercise_id: string; owner_user_id: string;
  source_files: SourceFileInput[]; entrypoint: string; is_formal: boolean;
  status: SubmissionStatus; created_at: string; request_id: string;
}
export interface CompilerDiagnostic {
  severity: string; message: string; code: string | null; file: string | null;
  start_line: number | null; start_column: number | null; end_line: number | null; end_column: number | null;
}
export interface ExecutionResult {
  submission_id: string; protocol_version: "2";
  status: "succeeded" | "compile_failed" | "run_failed" | "timed_out" | "resource_exhausted";
  phase: "compile" | "run" | "control"; retryable: boolean; exit_code: number | null; signal: number | null;
  stdout: string; stderr: string; stdout_truncated: boolean; stderr_truncated: boolean;
  diagnostics: CompilerDiagnostic[]; command_summary: { compiler: "cjc"; source_count: number; entrypoint: string; output_kind: "executable" };
  limits: { timeout_ms: number; max_output_chars: number; max_files: number; max_source_bytes: number; pids: number; memory_bytes: number; cpu_cores: number };
  toolchain: { cjc: string; cjpm: string; backend: "cjnative" }; created_at: string; request_id: string;
  rule_matches: Array<{ misconception_id: string; root_concept_id: string; related_concept_ids: string[]; diagnostic_indices: number[]; evidence_kind: "compiler_diagnostic"; evidence_summary: string; source_references: string[]; match_strength: "strong" | "weak" }>;
}
export interface EvidenceBinding { kind: "compiler_diagnostic" | "rule_match" | "approved_knowledge"; summary: string; diagnostic_index?: number; misconception_id?: string; source_reference?: string }
export interface Diagnosis {
  diagnosis_id: string; submission_id: string; course_id: string; owner_user_id: string;
  category: "conceptual" | "strategic" | "procedural" | "expression";
  locations: Array<{ file: string; start_line: number; end_line: number }>;
  concept_ids: string[]; root_cause: string; evidence: EvidenceBinding[]; confidence: number;
  recommended_hint_level: number; requires_teacher_review: boolean; created_at: string; request_id: string;
}
export interface HintEvent { hint_event_id: string; diagnosis_id: string; previous_level: number; current_level: number; reason: string; previous_attempt_count: number; content: string; used_safe_fallback: boolean; created_at: string; request_id: string }
export interface ExplanationCheck { explanation_check_id: string; diagnosis_id: string; understands: boolean; concept_ids: string[]; evidence_summary: string; confidence: number; feedback: string; memory_proposal_eligible: boolean; created_at: string; request_id: string }
export interface MemoryProposal { proposal_id: string; root_proposal_id: string; previous_proposal_id: string | null; version: number; owner_user_id: string; course_id: string; diagnosis_id: string; explanation_check_id: string; content: string; concept_ids: string[]; confidence: number; status: "pending" | "accepted" | "rejected" | "superseded" | "expired"; created_at: string; expires_at: string; request_id: string }
export interface LearningMemory { memory_id: string; logical_memory_id: string; previous_version_id: string | null; version: number; owner_user_id: string; course_id: string; memory_type: string; visibility: "private"; content: string | null; concept_ids: string[]; source_diagnosis_id: string; confidence: number; allowed_purposes: string[]; status: "active" | "superseded" | "expired" | "deletion_pending" | "deleted"; created_at: string; updated_at: string; expires_at: string | null; request_id: string }
export interface DeletionReceipt { deletion_id: string; memory_id: string; owner_user_id: string; course_id: string; status: "deletion_pending" | "deleted"; requested_at: string; completed_at: string | null; attempts: number; index_cleared: boolean; cache_cleared: boolean; model_references_cleared: boolean; reverse_lookup_absent: boolean; error_code: string | null; request_id: string }
export interface TeacherFilters { concept_id: string | null; exercise_id: string | null; start_at: string | null; end_at: string | null }
export interface TeacherAnalyticsGroup { concept_id: string; exercise_id: string | null; category: string; sample_size: number; diagnosis_count: number; independent_repair_count: number }
export type TeacherAnalytics =
  | { status: "available"; course_id: string; filters: TeacherFilters; minimum_sample_size: 5; sample_size: number; groups: TeacherAnalyticsGroup[] }
  | { status: "insufficient_sample"; course_id: string; filters: TeacherFilters; minimum_sample_size: 5 };
export interface TeacherReviewQueueItem { queue_event_id: string; diagnosis_id: string; submission_id: string; exercise_id: string; category: string; concept_ids: string[]; root_cause: string; evidence_summaries: string[]; confidence: number; review_reason: string; queued_at: string }
export interface TeacherReviewQueue { course_id: string; filters: TeacherFilters; items: TeacherReviewQueueItem[] }
export type TeacherReviewDecision = "confirmed" | "overturned" | "insufficient_evidence";
export interface TeacherDiagnosisReview { diagnosis_id: string; course_id: string; reviewer_user_id: string; decision: TeacherReviewDecision; reason: string; reviewed_at: string }
export type ModelProviderName = "environment" | "deepseek" | "qwen" | "openai_compatible" | "mock" | "disabled";
export interface ModelSettingsView {
  provider: string; model: string; base_url: string;
  source: "environment" | "web"; configured: boolean; key_hint: string | null;
  timeout_seconds: number; persistence: "file" | "memory"; environment_locked: boolean;
}
export interface ModelSettingsUpdate {
  provider: ModelProviderName; model: string; base_url: string; api_key: string; timeout_seconds: number;
}
export type ModelProbeStatus = "ok" | "invalid_credentials" | "model_or_endpoint_not_found" | "rate_limited" | "rejected_request" | "timeout" | "transport_error" | "http_error";
export interface ModelProbeResult { status: ModelProbeStatus; http_status: number | null }
export type ModelSettingsScope = "shared" | "own";
export interface SharedModelSummary { provider: string; model: string; configured: boolean }
export interface PersonalModelSettingsView {
  scope: ModelSettingsScope; provider: string; model: string; base_url: string;
  source: "environment" | "web"; configured: boolean; key_hint: string | null;
  timeout_seconds: number; personal_configured: boolean; shared: SharedModelSummary;
  persistence: "file" | "memory"; environment_locked: boolean;
}
export interface PersonalModelSettingsUpdate {
  mode: ModelSettingsScope; provider?: ModelProviderName; model?: string;
  base_url?: string; api_key?: string; timeout_seconds?: number;
}
export interface ErrorEnvelope { code: string; message: string; request_id: string }

export class ApiError extends Error {
  constructor(public readonly status: number, public readonly envelope: ErrorEnvelope) {
    super(envelope.message);
    this.name = "ApiError";
  }
  get requestId() { return this.envelope.request_id; }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function createIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `kb-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function queryString(values: Record<string, string | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => { if (value) query.set(key, value); });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export class ApiClient {
  constructor(
    private readonly baseUrl: string,
    private readonly getAccessToken: () => string | null,
  ) {}

  private async request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
    const headers = new Headers(init.headers);
    if (init.body) headers.set("Content-Type", "application/json");
    const token = this.getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers, signal });
    const body = await response.json().catch(() => null) as T | ErrorEnvelope | null;
    if (!response.ok) {
      const candidate = body as Partial<ErrorEnvelope> | null;
      throw new ApiError(response.status, {
        code: candidate?.code ?? "HTTP_ERROR",
        message: candidate?.message ?? "请求未完成",
        request_id: candidate?.request_id ?? response.headers.get("x-request-id") ?? "unknown",
      });
    }
    return body as T;
  }

  login(username: string, password: string, signal?: AbortSignal) {
    return this.request<LoginResponse>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }, signal);
  }
  async logout() { await this.request<void>("/auth/logout", { method: "POST" }); }
  listCourses(signal?: AbortSignal) { return this.request<CourseSummary[]>("/courses", {}, signal); }
  listExercises(courseId: string, signal?: AbortSignal) { return this.request<ExerciseSummary[]>(`/courses/${encodeURIComponent(courseId)}/exercises`, {}, signal); }
  createSubmission(exerciseId: string, content: string, signal?: AbortSignal) {
    return this.request<Submission>(`/exercises/${encodeURIComponent(exerciseId)}/submissions`, { method: "POST", body: JSON.stringify({ source_files: [{ path: "main.cj", content }], entrypoint: "main.cj", is_formal: true }) }, signal);
  }
  getSubmission(submissionId: string, signal?: AbortSignal) { return this.request<Submission>(`/submissions/${encodeURIComponent(submissionId)}`, {}, signal); }
  getExecutionResult(submissionId: string, signal?: AbortSignal) { return this.request<ExecutionResult>(`/submissions/${encodeURIComponent(submissionId)}/execution-result`, {}, signal); }
  getDiagnosis(submissionId: string, signal?: AbortSignal) { return this.request<Diagnosis>(`/submissions/${encodeURIComponent(submissionId)}/diagnosis`, {}, signal); }
  recordAttempt(diagnosisId: string, submissionId: string, signal?: AbortSignal) { return this.request<void>(`/diagnoses/${encodeURIComponent(diagnosisId)}/attempts`, { method: "POST", body: JSON.stringify({ submission_id: submissionId }) }, signal); }
  nextHint(diagnosisId: string, reason: string, signal?: AbortSignal) { return this.request<HintEvent>(`/diagnoses/${encodeURIComponent(diagnosisId)}/hints/next`, { method: "POST", body: JSON.stringify({ reason }) }, signal); }
  checkExplanation(diagnosisId: string, explanation: string, signal?: AbortSignal) { return this.request<ExplanationCheck>(`/diagnoses/${encodeURIComponent(diagnosisId)}/explanation-check`, { method: "POST", body: JSON.stringify({ explanation }) }, signal); }
  listMemoryProposals(courseId: string, signal?: AbortSignal) { return this.request<MemoryProposal[]>(`/me/memory-proposals${queryString({ course_id: courseId })}`, {}, signal); }
  acceptProposal(proposalId: string, signal?: AbortSignal, key = createIdempotencyKey()) { return this.request<LearningMemory>(`/memory-proposals/${encodeURIComponent(proposalId)}/accept`, { method: "POST", headers: { "Idempotency-Key": key } }, signal); }
  rejectProposal(proposalId: string, signal?: AbortSignal, key = createIdempotencyKey()) { return this.request<MemoryProposal>(`/memory-proposals/${encodeURIComponent(proposalId)}/reject`, { method: "POST", headers: { "Idempotency-Key": key } }, signal); }
  correctProposal(proposalId: string, content: string, signal?: AbortSignal, key = createIdempotencyKey()) { return this.request<MemoryProposal>(`/memory-proposals/${encodeURIComponent(proposalId)}`, { method: "PATCH", headers: { "Idempotency-Key": key }, body: JSON.stringify({ content }) }, signal); }
  listMemories(courseId: string, signal?: AbortSignal) { return this.request<LearningMemory[]>(`/me/memories${queryString({ course_id: courseId, purpose: "learning_support" })}`, {}, signal); }
  correctMemory(memoryId: string, content: string, signal?: AbortSignal, key = createIdempotencyKey()) { return this.request<LearningMemory>(`/memories/${encodeURIComponent(memoryId)}`, { method: "PATCH", headers: { "Idempotency-Key": key }, body: JSON.stringify({ content }) }, signal); }
  deleteMemory(memoryId: string, signal?: AbortSignal, key = createIdempotencyKey()) { return this.request<DeletionReceipt>(`/memories/${encodeURIComponent(memoryId)}`, { method: "DELETE", headers: { "Idempotency-Key": key } }, signal); }
  getDeletion(deletionId: string, signal?: AbortSignal) { return this.request<DeletionReceipt>(`/memory-deletions/${encodeURIComponent(deletionId)}`, {}, signal); }
  getTeacherAnalytics(courseId: string, filters: TeacherFilters, signal?: AbortSignal) { return this.request<TeacherAnalytics>(`/teacher/courses/${encodeURIComponent(courseId)}/analytics${queryString({ ...filters })}`, {}, signal); }
  getTeacherReviewQueue(courseId: string, filters: TeacherFilters, signal?: AbortSignal) { return this.request<TeacherReviewQueue>(`/teacher/courses/${encodeURIComponent(courseId)}/review-queue${queryString({ ...filters })}`, {}, signal); }
  reviewDiagnosis(diagnosisId: string, decision: TeacherReviewDecision, reason: string, signal?: AbortSignal) { return this.request<TeacherDiagnosisReview>(`/teacher/diagnoses/${encodeURIComponent(diagnosisId)}/review`, { method: "POST", body: JSON.stringify({ decision, reason }) }, signal); }
  getModelSettings(signal?: AbortSignal) { return this.request<ModelSettingsView>("/teacher/model-settings", {}, signal); }
  updateModelSettings(update: ModelSettingsUpdate, signal?: AbortSignal) {
    return this.request<ModelSettingsView>("/teacher/model-settings", { method: "PUT", body: JSON.stringify(update) }, signal);
  }
  probeModelSettings(update: ModelSettingsUpdate, signal?: AbortSignal) {
    return this.request<ModelProbeResult>("/teacher/model-settings/probe", { method: "POST", body: JSON.stringify(update) }, signal);
  }
  getMyModelSettings(signal?: AbortSignal) { return this.request<PersonalModelSettingsView>("/model-settings", {}, signal); }
  updateMyModelSettings(update: PersonalModelSettingsUpdate, signal?: AbortSignal) {
    return this.request<PersonalModelSettingsView>("/model-settings", { method: "PUT", body: JSON.stringify(update) }, signal);
  }
  probeMyModelSettings(update: PersonalModelSettingsUpdate, signal?: AbortSignal) {
    return this.request<ModelProbeResult>("/model-settings/probe", { method: "POST", body: JSON.stringify(update) }, signal);
  }
}
