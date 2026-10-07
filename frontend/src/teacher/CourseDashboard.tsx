import { useCallback, useEffect, useState } from "react";

import type { ApiClient, CourseSummary, TeacherAnalytics, TeacherFilters } from "../api/client";
import { RequestState } from "../components/RequestState";
import { ReviewQueue } from "./ReviewQueue";

interface FilterDraft { conceptId: string; exerciseId: string; startDate: string; endDate: string }
const emptyFilters: TeacherFilters = { concept_id: null, exercise_id: null, start_at: null, end_at: null };
const emptyDraft: FilterDraft = { conceptId: "", exerciseId: "", startDate: "", endDate: "" };

function startOfLocalDay(value: string) { return value ? new Date(`${value}T00:00:00`).toISOString() : null; }
function endOfLocalDay(value: string) { return value ? new Date(`${value}T23:59:59.999`).toISOString() : null; }

function precedingWindow(filters: TeacherFilters): TeacherFilters | null {
  if (!filters.start_at || !filters.end_at) return null;
  const start = new Date(filters.start_at).getTime();
  const end = new Date(filters.end_at).getTime();
  const duration = end - start;
  if (!Number.isFinite(duration) || duration < 0) return null;
  const previousEnd = start - 1;
  return { ...filters, start_at: new Date(previousEnd - duration).toISOString(), end_at: new Date(previousEnd).toISOString() };
}

function totals(value: TeacherAnalytics) {
  if (value.status !== "available") return null;
  return value.groups.reduce((sum, group) => ({ diagnoses: sum.diagnoses + group.diagnosis_count, repairs: sum.repairs + group.independent_repair_count }), { diagnoses: 0, repairs: 0 });
}

export function CourseDashboard({ api }: { api: ApiClient }) {
  const [courses, setCourses] = useState<CourseSummary[]>([]);
  const [courseId, setCourseId] = useState("");
  const [draft, setDraft] = useState<FilterDraft>(emptyDraft);
  const [filters, setFilters] = useState<TeacherFilters>(emptyFilters);
  const [analytics, setAnalytics] = useState<TeacherAnalytics | null>(null);
  const [comparison, setComparison] = useState<TeacherAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const loadCourses = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError(null);
    try { const next = await api.listCourses(signal); if (!signal?.aborted) { setCourses(next); setCourseId((current) => current || next[0]?.course_id || ""); } }
    catch (nextError) { if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [api]);

  useEffect(() => { const controller = new AbortController(); void loadCourses(controller.signal); return () => controller.abort(); }, [loadCourses]);

  const loadAnalytics = useCallback(async (signal?: AbortSignal) => {
    if (!courseId) return;
    setAnalyticsLoading(true); setAnalytics(null); setComparison(null); setError(null);
    try {
      const current = await api.getTeacherAnalytics(courseId, filters, signal);
      if (signal?.aborted) return;
      setAnalytics(current);
      const previousFilters = precedingWindow(filters);
      if (previousFilters) {
        const previous = await api.getTeacherAnalytics(courseId, previousFilters, signal);
        if (!signal?.aborted) setComparison(previous);
      }
    } catch (nextError) { if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError); }
    finally { if (!signal?.aborted) setAnalyticsLoading(false); }
  }, [api, courseId, filters]);

  useEffect(() => { const controller = new AbortController(); void loadAnalytics(controller.signal); return () => controller.abort(); }, [loadAnalytics]);

  function applyFilters() {
    setFilters({ concept_id: draft.conceptId || null, exercise_id: draft.exerciseId || null, start_at: startOfLocalDay(draft.startDate), end_at: endOfLocalDay(draft.endDate) });
  }

  const currentTotals = analytics ? totals(analytics) : null;
  const comparisonTotals = comparison ? totals(comparison) : null;

  return (
    <div className="teacher-layout">
      <header className="page-heading teacher-heading"><div><p className="section-kicker">TEACHER · COURSE SIGNALS</p><h1>课程诊断台</h1><p>观察匿名群体概念信号，复核证据不足的诊断。</p></div><span className="course-mark">《仓颉语言设计》</span></header>
      {loading && <p role="status">正在读取课程…</p>}
      {error !== null && <RequestState error={error} retry={() => void (courses.length ? loadAnalytics() : loadCourses())} retryLabel="重试课程数据" deniedLabel="无法访问该课程资源" />}
      {!loading && !error && courses.length === 0 && <div className="empty-panel"><strong>还没有可管理的课程</strong></div>}
      {courseId && <>
        <section className="filter-rail" aria-label="分析筛选">
          <label>课程<select value={courseId} onChange={(event) => setCourseId(event.target.value)}>{courses.map((course) => <option key={course.course_id} value={course.course_id}>{course.title}</option>)}</select></label>
          <label>概念<input value={draft.conceptId} onChange={(event) => setDraft((current) => ({ ...current, conceptId: event.target.value }))} placeholder="概念 ID" /></label>
          <label>练习<input value={draft.exerciseId} onChange={(event) => setDraft((current) => ({ ...current, exerciseId: event.target.value }))} placeholder="练习 ID" /></label>
          <label>开始日期<input type="date" value={draft.startDate} onChange={(event) => setDraft((current) => ({ ...current, startDate: event.target.value }))} /></label>
          <label>结束日期<input type="date" value={draft.endDate} min={draft.startDate || undefined} onChange={(event) => setDraft((current) => ({ ...current, endDate: event.target.value }))} /></label>
          <button type="button" onClick={applyFilters} disabled={Boolean(draft.startDate && draft.endDate && draft.startDate > draft.endDate)}>应用筛选</button>
        </section>
        {analyticsLoading && <p role="status">正在生成匿名分析…</p>}
        {analytics !== null && <section className="analytics-section" aria-labelledby="analytics-title">
          <div className="section-heading"><div><p className="section-kicker">ANONYMOUS AGGREGATE</p><h2 id="analytics-title">匿名概念误区分析</h2></div><span className="privacy-chip">最低样本阈值 5</span></div>
          <p className="privacy-note">只显示达到隐私阈值的群体聚合。未达阈值时不会透露精确人数。</p>
          {analytics.status === "insufficient_sample" && <div className="suppressed-state" role="status"><svg viewBox="0 0 48 48" aria-hidden="true"><path d="M12 22v-6a12 12 0 0 1 24 0v6M9 22h30v20H9z" /></svg><div><strong>样本不足</strong><p>当前筛选范围未达到匿名展示阈值。扩大时间范围或移除部分筛选后再试。</p></div></div>}
          {analytics.status === "available" && <div className="analytics-grid"><div className="signal-summary"><span>有效匿名样本</span><strong>{analytics.sample_size}</strong><small>仅聚合统计</small></div><div className="table-scroll"><table aria-label="匿名概念误区数据"><thead><tr><th>概念</th><th>练习</th><th>类型</th><th>诊断次数</th><th>独立修复</th></tr></thead><tbody>{analytics.groups.map((group) => <tr key={`${group.concept_id}-${group.exercise_id ?? "all"}`}><td data-label="概念">{group.concept_id}</td><td data-label="练习">{group.exercise_id ?? "全部"}</td><td data-label="类型">{group.category}</td><td data-label="诊断次数">{group.diagnosis_count}</td><td data-label="独立修复">{group.independent_repair_count}</td></tr>)}</tbody></table></div></div>}
          {precedingWindow(filters) && <section className="trend-section" aria-labelledby="trend-title"><h3 id="trend-title">相邻时间窗口趋势</h3><p>当前筛选窗口与等长前一窗口的匿名聚合对照。</p>{comparison === null ? <p role="status">正在生成对照窗口…</p> : comparison.status === "insufficient_sample" || analytics.status === "insufficient_sample" ? <div className="suppressed-state"><strong>对照窗口样本不足</strong><p>为保护隐私，不显示任一受抑制窗口的精确人数。</p></div> : <table aria-label="相邻时间窗口趋势数据"><thead><tr><th>窗口</th><th>诊断次数</th><th>独立修复</th></tr></thead><tbody><tr><td data-label="窗口">当前窗口</td><td data-label="诊断次数">{currentTotals?.diagnoses}</td><td data-label="独立修复">{currentTotals?.repairs}</td></tr><tr><td data-label="窗口">前一窗口</td><td data-label="诊断次数">{comparisonTotals?.diagnoses}</td><td data-label="独立修复">{comparisonTotals?.repairs}</td></tr></tbody></table>}</section>}
        </section>}
        <ReviewQueue api={api} courseId={courseId} filters={filters} />
      </>}
    </div>
  );
}
