import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, type ApiClient, type TeacherFilters, type TeacherReviewDecision, type TeacherReviewQueueItem } from "../api/client";
import { RequestState } from "../components/RequestState";

interface ReviewForm { decision: TeacherReviewDecision; reason: string }

export function ReviewQueue({ api, courseId, filters }: { api: ApiClient; courseId: string; filters: TeacherFilters }) {
  const [items, setItems] = useState<TeacherReviewQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [processed, setProcessed] = useState<string[]>([]);
  const [forms, setForms] = useState<Record<string, ReviewForm>>({});
  const [busyIds, setBusyIds] = useState<string[]>([]);
  const busyRef = useRef(new Set<string>());

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError(null); setProcessed([]); setForms({}); busyRef.current.clear(); setBusyIds([]);
    try { setItems((await api.getTeacherReviewQueue(courseId, filters, signal)).items); }
    catch (nextError) { if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [api, courseId, filters]);

  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);

  function formFor(id: string): ReviewForm { return forms[id] ?? { decision: "confirmed", reason: "" }; }
  function updateForm(id: string, patch: Partial<ReviewForm>) { setForms((current) => ({ ...current, [id]: { ...formFor(id), ...current[id], ...patch } })); }

  async function review(item: TeacherReviewQueueItem) {
    const form = formFor(item.diagnosis_id);
    if (!form.reason.trim() || busyRef.current.has(item.diagnosis_id)) return;
    busyRef.current.add(item.diagnosis_id); setBusyIds(Array.from(busyRef.current)); setError(null);
    try {
      await api.reviewDiagnosis(item.diagnosis_id, form.decision, form.reason.trim());
      setProcessed((current) => [...current, item.diagnosis_id]);
    } catch (nextError) {
      if (nextError instanceof ApiError && nextError.status === 409) setError(new ApiError(409, { ...nextError.envelope, message: "该诊断已被处理，请刷新队列" }));
      else setError(nextError);
    } finally { busyRef.current.delete(item.diagnosis_id); setBusyIds(Array.from(busyRef.current)); }
  }

  return (
    <section className="review-section" aria-labelledby="review-title">
      <div className="section-heading"><div><p className="section-kicker">TEACHER REVIEW</p><h2 id="review-title">低置信度复核队列</h2></div><span className="privacy-chip">去标识摘要</span></div>
      <p className="privacy-note">仅展示本次诊断证据与概念归因，不提供学生身份、私人对话或个人记忆。</p>
      {loading && <p role="status">正在读取复核队列…</p>}
      {error !== null && (error instanceof ApiError && error.status === 409 ? <div className="request-state is-warning" role="alert"><strong>{error.envelope.message}</strong><p className="request-id">请求编号：{error.requestId}</p><button type="button" className="button-secondary" onClick={() => void load()}>刷新队列</button></div> : <RequestState error={error} retry={() => void load()} retryLabel="重试复核队列" deniedLabel="无法访问该课程资源" />)}
      {!loading && !error && items.length === 0 && <div className="empty-panel"><strong>当前没有待复核诊断</strong><p>新的低置信度诊断会自动进入这里。</p></div>}
      <div className="review-list">{items.map((item) => {
        const form = formFor(item.diagnosis_id);
        const busy = busyIds.includes(item.diagnosis_id);
        return <article key={item.queue_event_id} className="review-item">
          <div className="review-item-head"><span className="status-badge status-warning">置信度 {Math.round(item.confidence * 100)}%</span><small>{item.exercise_id}</small></div>
          <h3>{item.root_cause}</h3><p className="concept-code">{item.concept_ids.join(" · ")}</p>
          <ul>{item.evidence_summaries.map((summary) => <li key={summary}>{summary}</li>)}</ul><p className="review-reason">入队原因：{item.review_reason}</p>
          {processed.includes(item.diagnosis_id) ? <p className="notice" role="status">已处理</p> : <div className="review-form">
            <label>复核决定<select value={form.decision} onChange={(event) => updateForm(item.diagnosis_id, { decision: event.target.value as TeacherReviewDecision })} disabled={busy}><option value="confirmed">确认诊断</option><option value="overturned">推翻诊断</option><option value="insufficient_evidence">证据不足</option></select></label>
            <label>复核理由<textarea value={form.reason} onChange={(event) => updateForm(item.diagnosis_id, { reason: event.target.value })} placeholder="说明判断所依据的课程概念或证据" disabled={busy} /></label>
            <button type="button" onClick={() => void review(item)} disabled={busy || !form.reason.trim()}>{busy ? "正在提交…" : "提交复核"}</button>
          </div>}
        </article>;
      })}</div>
    </section>
  );
}
