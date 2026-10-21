import { useState } from "react";

import type { ApiClient, Diagnosis, ExplanationCheck, HintEvent } from "../api/client";
import { RequestState } from "../components/RequestState";

export function DiagnosisPanel({ api, diagnosis, onExplanationChecked }: { api: ApiClient; diagnosis: Diagnosis; onExplanationChecked: (understands: boolean) => void }) {
  const [hints, setHints] = useState<HintEvent[]>([]);
  const [explanation, setExplanation] = useState("");
  const [check, setCheck] = useState<ExplanationCheck | null>(null);
  const [busy, setBusy] = useState<"hint" | "check" | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function requestHint() {
    setBusy("hint"); setError(null);
    try {
      const hint = await api.nextHint(diagnosis.diagnosis_id, "student-requested-more-guidance");
      setHints((current) => [...current, hint]);
    }
    catch (nextError) { setError(nextError); }
    finally { setBusy(null); }
  }

  async function verifyExplanation() {
    if (!explanation.trim()) return;
    setBusy("check"); setError(null);
    try {
      const result = await api.checkExplanation(diagnosis.diagnosis_id, explanation.trim());
      setCheck(result);
      onExplanationChecked(result.understands);
    } catch (nextError) { setError(nextError); }
    finally { setBusy(null); }
  }

  return (
    <section className="diagnosis-panel" aria-labelledby="diagnosis-title">
      <div className="section-heading">
        <div><p className="section-kicker">概念根因</p><h2 id="diagnosis-title">结构化误区诊断</h2></div>
        <span className={`status-badge ${diagnosis.requires_teacher_review ? "status-warning" : "status-success"}`}>
          {diagnosis.requires_teacher_review ? "等待教师复核" : `置信度 ${Math.round(diagnosis.confidence * 100)}%`}
        </span>
      </div>
      {diagnosis.requires_teacher_review && <p className="privacy-note">当前结论置信度较低，不会写入长期记忆；教师只能看到本次去标识诊断摘要。</p>}
      <p className="root-cause">{diagnosis.root_cause}</p>
      <dl className="diagnosis-meta">
        <div><dt>类别</dt><dd>{diagnosis.category}</dd></div>
        <div><dt>相关概念</dt><dd>{diagnosis.concept_ids.join(" · ")}</dd></div>
      </dl>
      <div className="evidence-list">
        <h3>证据</h3>
        <ul>{diagnosis.evidence.map((item, index) => <li key={`${item.kind}-${index}`}><span>{item.kind}</span>{item.summary}</li>)}</ul>
      </div>
      <div className="hint-ladder">
        <div className="subsection-heading"><h3>提示阶梯</h3><button type="button" onClick={requestHint} disabled={busy !== null || hints.at(-1)?.current_level === 4}>请求下一层提示</button></div>
        {hints.length === 0 ? <p className="empty-copy">先自己再试一次；需要时再逐级展开提示。</p> : hints.map((hint) => <article key={hint.hint_event_id} className="hint"><strong>第 {hint.current_level} 级提示</strong><p>{hint.content}</p>{hint.used_safe_fallback && <small>当前使用安全备用提示</small>}</article>)}
      </div>
      <div className="explanation-check">
        <label htmlFor="student-explanation">我对错误原因的解释</label>
        <textarea id="student-explanation" value={explanation} onChange={(event) => setExplanation(event.target.value)} placeholder="用自己的话说明概念根因，而不是只描述修改步骤。" />
        <button type="button" onClick={verifyExplanation} disabled={busy !== null || !explanation.trim()}>验证我的理解</button>
        {check && <div className={`understanding-result ${check.understands ? "is-understood" : ""}`} role="status"><strong>{check.understands ? "理解验证通过" : "还需要再想一步"}</strong><p>{check.feedback}</p>{check.memory_proposal_eligible && <p>可以生成记忆建议</p>}</div>}
      </div>
      {error !== null && <RequestState error={error} />}
    </section>
  );
}
