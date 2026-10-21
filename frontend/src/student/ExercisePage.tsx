import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { ApiClient, CourseSummary, Diagnosis, ExecutionResult, ExerciseSummary } from "../api/client";
import { ConceptTrace } from "../components/ConceptTrace";
import { RequestState } from "../components/RequestState";
import { DiagnosisPanel } from "./DiagnosisPanel";
import { MemoryCenter } from "./MemoryCenter";
import { useCodeDraft } from "./useCodeDraft";

const starter = `main() {
    // 在这里编写仓颉代码
}`;

const executionLabels: Record<ExecutionResult["status"], string> = {
  succeeded: "执行成功",
  compile_failed: "编译未通过",
  run_failed: "运行失败",
  timed_out: "执行超时",
  resource_exhausted: "资源限制中止",
};

export function ExercisePage({ api, ownerId }: { api: ApiClient; ownerId: string }) {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [courseId, setCourseId] = useState("");
  const [exercises, setExercises] = useState<ExerciseSummary[]>([]);
  const [exerciseId, setExerciseId] = useState("");
  const { source, updateSource, clearDraft, draftStatus } = useCodeDraft(ownerId, courseId, exerciseId, starter);
  const [loading, setLoading] = useState(true);
  const [courseError, setCourseError] = useState<unknown>(null);
  const [runError, setRunError] = useState<unknown>(null);
  const [running, setRunning] = useState(false);
  const [submissionId, setSubmissionId] = useState<string | null>(null);
  const [executionUnavailable, setExecutionUnavailable] = useState(false);
  const [execution, setExecution] = useState<ExecutionResult | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [attemptLinked, setAttemptLinked] = useState(false);
  const [understandingChecked, setUnderstandingChecked] = useState(false);
  const [memoryConfirmed, setMemoryConfirmed] = useState(false);
  const [memoryRefresh, setMemoryRefresh] = useState(0);
  const courseRequest = useRef<AbortController | null>(null);
  const resultRequest = useRef<AbortController | null>(null);
  const selectedCourse = useRef("");

  function clearLearningResult() {
    resultRequest.current?.abort();
    setRunning(false);
    setSubmissionId(null); setExecution(null); setDiagnosis(null); setRunError(null);
    setAttemptLinked(false);
    setExecutionUnavailable(false); setUnderstandingChecked(false); setMemoryConfirmed(false);
  }

  const loadCourses = useCallback(async () => {
    courseRequest.current?.abort();
    const controller = new AbortController();
    courseRequest.current = controller;
    setLoading(true); setCourseError(null);
    try {
      const nextCourses = await api.listCourses(controller.signal);
      if (controller.signal.aborted) return;
      setCourses(nextCourses);
      const nextCourse = nextCourses[0]?.course_id ?? "";
      selectedCourse.current = nextCourse;
      setCourseId(nextCourse);
      const nextExercises = nextCourse ? await api.listExercises(nextCourse, controller.signal) : [];
      if (controller.signal.aborted || selectedCourse.current !== nextCourse) return;
      setExercises(nextExercises); setExerciseId(nextExercises[0]?.exercise_id ?? "");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setCourseError(error);
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }, [api]);

  useEffect(() => {
    void loadCourses();
    return () => { courseRequest.current?.abort(); resultRequest.current?.abort(); };
  }, [loadCourses]);

  async function changeCourse(nextCourseId: string) {
    courseRequest.current?.abort();
    const controller = new AbortController();
    courseRequest.current = controller;
    selectedCourse.current = nextCourseId;
    setCourseId(nextCourseId); setExerciseId(""); setExercises([]); setCourseError(null); setLoading(true);
    clearLearningResult();
    try {
      const nextExercises = await api.listExercises(nextCourseId, controller.signal);
      if (controller.signal.aborted || selectedCourse.current !== nextCourseId) return;
      setExercises(nextExercises); setExerciseId(nextExercises[0]?.exercise_id ?? "");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) setCourseError(error);
    } finally { if (!controller.signal.aborted) setLoading(false); }
  }

  async function readDiagnosis(id: string) {
    resultRequest.current?.abort();
    const controller = new AbortController();
    resultRequest.current = controller;
    setRunning(true); setRunError(null);
    try { setDiagnosis(await api.getDiagnosis(id, controller.signal)); }
    catch (error) { if (!(error instanceof DOMException && error.name === "AbortError")) setRunError(error); }
    finally { if (!controller.signal.aborted) setRunning(false); }
  }

  async function readResults(id: string, controller: AbortController, original: Diagnosis | null = diagnosis) {
    try {
      const nextExecution = await api.getExecutionResult(id, controller.signal);
      if (controller.signal.aborted) return;
      setExecution(nextExecution);
      if (original && original.submission_id !== id) {
        await api.recordAttempt(original.diagnosis_id, id, controller.signal);
        if (!controller.signal.aborted) setAttemptLinked(true);
        return;
      }
      try { setDiagnosis(await api.getDiagnosis(id, controller.signal)); }
      catch (error) { if (!(error instanceof DOMException && error.name === "AbortError")) setRunError(error); }
    } catch (error) { if (!(error instanceof DOMException && error.name === "AbortError")) setRunError(error); }
  }

  async function retryResults(id: string) {
    resultRequest.current?.abort();
    const controller = new AbortController();
    resultRequest.current = controller;
    setRunning(true); setRunError(null);
    try { await readResults(id, controller); }
    finally { if (!controller.signal.aborted) setRunning(false); }
  }

  async function submit() {
    if (!exerciseId || !source.trim() || running) return;
    resultRequest.current?.abort();
    const controller = new AbortController();
    resultRequest.current = controller;
    const original = memoryConfirmed ? null : diagnosis;
    setDiagnosis(original);
    setRunning(true); setRunError(null); setExecution(null); setSubmissionId(null); setAttemptLinked(false);
    setExecutionUnavailable(false);
    if (!original) { setUnderstandingChecked(false); setMemoryConfirmed(false); }
    try {
      const submission = await api.createSubmission(exerciseId, source, controller.signal);
      if (controller.signal.aborted) return;
      setSubmissionId(submission.submission_id);
      if (submission.status === "execution_unavailable") { setExecutionUnavailable(true); return; }
      const durableSubmission = await api.getSubmission(submission.submission_id, controller.signal);
      if (durableSubmission.status === "execution_unavailable") { setExecutionUnavailable(true); return; }
      await readResults(submission.submission_id, controller, original);
    } catch (error) { if (!(error instanceof DOMException && error.name === "AbortError")) setRunError(error); }
    finally { if (!controller.signal.aborted) setRunning(false); }
  }

  const activeStep = useMemo(() => memoryConfirmed ? 5 : understandingChecked ? 4 : diagnosis ? 3 : execution ? 2 : running ? 1 : 0, [diagnosis, execution, memoryConfirmed, running, understandingChecked]);
  const resultIsSuccess = execution?.status === "succeeded";

  return (
    <div className="student-layout">
      <section className="workspace-column" aria-labelledby="student-workspace-title">
        <div className="page-heading"><div><p className="section-kicker">STUDENT · LEARNING LOOP</p><h1 id="student-workspace-title">学生工作台</h1><p>从真实编译证据出发，沿概念脉络完成一次可核验的学习闭环。</p></div><span className="course-mark">《仓颉语言设计》</span></div>
        <ConceptTrace activeStep={activeStep} />
        {loading && <div className="loading-line" role="status">正在准备课程与练习…</div>}
        {courseError !== null && <RequestState error={courseError} retry={() => void loadCourses()} retryLabel="重试加载课程" />}
        {!loading && !courseError && courses.length === 0 && <div className="empty-panel"><strong>课程尚未开放</strong><p>课程发布后，练习会出现在这里。</p></div>}
        {courses.length > 0 && <section className="code-workbench" aria-labelledby="code-title">
          <div className="workbench-bar"><div><p className="section-kicker">01 · 选择任务</p><h2 id="code-title">代码实验台</h2></div><div className="selector-row">
            <label>课程<select value={courseId} onChange={(event) => void changeCourse(event.target.value)}>{courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.title}</option>)}</select></label>
            <label>练习<select value={exerciseId} onChange={(event) => { setExerciseId(event.target.value); clearLearningResult(); }} disabled={exercises.length === 0}>{exercises.map((exercise) => <option key={exercise.exercise_id} value={exercise.exercise_id}>{exercise.title}</option>)}</select></label>
          </div></div>
          {exercises.length === 0 ? <p className="empty-copy">这个课程还没有可用练习。</p> : <><label className="editor-label" htmlFor="cangjie-source"><span>仓颉源码</span><small>main.cj · 隔离执行</small></label><textarea id="cangjie-source" aria-label="仓颉源码" className="code-editor" value={source} onChange={(event) => updateSource(event.target.value)} spellCheck={false} /><div className="submit-row"><p role="status">{draftStatus}</p><button type="button" className="text-button" disabled={running} onClick={() => { if (window.confirm("清除本机当前练习的代码草稿？已提交的作业和个人记忆不受影响。")) clearDraft(); }}>清除本机草稿</button></div><p className="privacy-note">草稿仅保存在当前浏览器，不会自动提交给教师。公用电脑使用后请清除草稿；临时测试网址更换后无法读取旧网址的草稿。</p><div className="submit-row"><p>代码只会发送到受限执行器，不在浏览器中模拟结果。</p><button type="button" onClick={() => void submit()} disabled={running || !source.trim()}>{running ? "正在隔离执行…" : "提交并运行"}</button></div></>}
        </section>}
        {executionUnavailable && <div className="request-state is-warning" role="status"><strong>执行服务暂不可用</strong><p>本次没有生成编译输出。源码仍保留在编辑器中，请稍后重试。</p></div>}
        {execution && <section className="execution-panel" aria-labelledby="execution-title">
          <div className="section-heading"><div><p className="section-kicker">02 · 执行证据</p><h2 id="execution-title">真实编译反馈</h2></div><span className={`status-badge ${resultIsSuccess ? "status-success" : "status-warning"}`}>{executionLabels[execution.status]}</span></div>
          <div className="compiler-strip"><span>阶段 {execution.phase}</span><span>cjc {execution.toolchain.cjc}</span><span>退出码 {execution.exit_code ?? "—"}</span><span>请求 {execution.request_id}</span></div>
          {execution.diagnostics.length > 0 && <ol className="compiler-diagnostics">{execution.diagnostics.map((item, index) => <li key={`${item.message}-${index}`}><strong>{item.file ?? "main.cj"}{item.start_line ? `:${item.start_line}` : ""}</strong><span>{item.message}</span></li>)}</ol>}
          {(execution.stdout || execution.stderr || execution.diagnostics.length === 0) && <div className="output-grid"><div><h3>标准输出{execution.stdout_truncated ? "（已截断）" : ""}</h3><pre className="console-output">{execution.stdout || "无输出"}</pre></div><div><h3>错误输出{execution.stderr_truncated ? "（已截断）" : ""}</h3><pre className="console-output error-output">{execution.stderr || "无输出"}</pre></div></div>}
        </section>}
        {attemptLinked && resultIsSuccess && <p role="status">修复提交已关联原诊断</p>}
        {runError !== null && <RequestState error={runError} retry={submissionId ? () => void (execution && (!diagnosis || diagnosis.submission_id === submissionId) ? readDiagnosis(submissionId) : retryResults(submissionId)) : () => void submit()} retryLabel={diagnosis && submissionId && diagnosis.submission_id !== submissionId ? "重试关联修复提交" : execution && submissionId ? "重新读取诊断" : "重新读取结果"} />}
        {diagnosis && <DiagnosisPanel key={diagnosis.diagnosis_id} api={api} diagnosis={diagnosis} onExplanationChecked={(understands) => { setUnderstandingChecked(understands); setMemoryRefresh((value) => value + 1); }} />}
      </section>
      {courseId && <aside className="memory-column"><MemoryCenter key={courseId} api={api} courseId={courseId} refreshKey={memoryRefresh} onMemoryConfirmed={() => setMemoryConfirmed(true)} /></aside>}
    </div>
  );
}
