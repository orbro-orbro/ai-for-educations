import { useCallback, useEffect, useRef, useState } from "react";

import { createIdempotencyKey, type ApiClient, type DeletionReceipt, type LearningMemory, type MemoryProposal } from "../api/client";
import { RequestState } from "../components/RequestState";

export function MemoryCenter({ api, courseId, refreshKey = 0, onMemoryConfirmed }: { api: ApiClient; courseId: string; refreshKey?: number; onMemoryConfirmed?: () => void }) {
  const [proposals, setProposals] = useState<MemoryProposal[]>([]);
  const [memories, setMemories] = useState<LearningMemory[]>([]);
  const [receipts, setReceipts] = useState<Record<string, DeletionReceipt>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busyIds, setBusyIds] = useState<string[]>([]);
  const busyRef = useRef(new Set<string>());
  const idempotencyKeys = useRef(new Map<string, string>());
  const mounted = useRef(true);
  const confirmButton = useRef<HTMLButtonElement | null>(null);
  const deleteTrigger = useRef<HTMLButtonElement | null>(null);

  const lock = (id: string) => {
    if (busyRef.current.has(id)) return false;
    busyRef.current.add(id); setBusyIds(Array.from(busyRef.current)); return true;
  };
  const unlock = (id: string) => {
    busyRef.current.delete(id);
    if (mounted.current) setBusyIds(Array.from(busyRef.current));
  };
  const keyFor = (id: string) => {
    const existing = idempotencyKeys.current.get(id);
    if (existing) return existing;
    const created = createIdempotencyKey();
    idempotencyKeys.current.set(id, created);
    return created;
  };

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError(null);
    try {
      const [nextProposals, nextMemories] = await Promise.all([api.listMemoryProposals(courseId, signal), api.listMemories(courseId, signal)]);
      if (signal?.aborted) return;
      setProposals(nextProposals.filter((item) => item.status === "pending"));
      setMemories((current) => {
        const pending = current.filter((item) => item.status === "deletion_pending" && !nextMemories.some((candidate) => candidate.memory_id === item.memory_id));
        return [...nextMemories.filter((item) => item.status !== "deleted"), ...pending];
      });
    } catch (nextError) { if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [api, courseId]);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void load(controller.signal);
    return () => { mounted.current = false; controller.abort(); };
  }, [load, refreshKey]);

  useEffect(() => { if (confirming) confirmButton.current?.focus(); }, [confirming]);

  function closeConfirmation() {
    setConfirming(null);
    queueMicrotask(() => deleteTrigger.current?.focus());
  }

  async function accept(item: MemoryProposal) {
    const lockId = `proposal:${item.proposal_id}`;
    if (!lock(lockId)) return;
    try {
      const saved = await api.acceptProposal(item.proposal_id, undefined, keyFor(`accept:${item.proposal_id}`));
      if (!mounted.current) return;
      setProposals((items) => items.filter((candidate) => candidate.proposal_id !== item.proposal_id));
      setMemories((items) => [saved, ...items.filter((candidate) => candidate.memory_id !== saved.memory_id)]);
      idempotencyKeys.current.delete(`accept:${item.proposal_id}`); setNotice("已保存到个人记忆"); onMemoryConfirmed?.();
    } catch (nextError) { if (mounted.current) setError(nextError); }
    finally { unlock(lockId); }
  }

  async function reject(item: MemoryProposal) {
    const lockId = `proposal:${item.proposal_id}`;
    if (!lock(lockId)) return;
    try { await api.rejectProposal(item.proposal_id, undefined, keyFor(`reject:${item.proposal_id}`)); if (mounted.current) { idempotencyKeys.current.delete(`reject:${item.proposal_id}`); setProposals((items) => items.filter((candidate) => candidate.proposal_id !== item.proposal_id)); setNotice("已拒绝这条记忆建议"); } }
    catch (nextError) { if (mounted.current) setError(nextError); }
    finally { unlock(lockId); }
  }

  async function saveCorrection(item: LearningMemory) {
    const lockId = `memory:${item.memory_id}`;
    if (!draft.trim() || !lock(lockId)) return;
    try { const operation = `correct:${item.memory_id}:${draft.trim()}`; const corrected = await api.correctMemory(item.memory_id, draft.trim(), undefined, keyFor(operation)); if (mounted.current) { idempotencyKeys.current.delete(operation); setMemories((items) => items.map((candidate) => candidate.memory_id === item.memory_id ? corrected : candidate)); setEditing(null); setNotice("记忆已按你的表述更新"); } }
    catch (nextError) { if (mounted.current) setError(nextError); }
    finally { unlock(lockId); }
  }

  async function confirmDelete(item: LearningMemory) {
    const lockId = `memory:${item.memory_id}`;
    if (!lock(lockId)) return;
    try {
      const receipt = await api.deleteMemory(item.memory_id, undefined, keyFor(`delete:${item.memory_id}`));
      if (!mounted.current) return;
      idempotencyKeys.current.delete(`delete:${item.memory_id}`); setReceipts((current) => ({ ...current, [item.memory_id]: receipt }));
      if (receipt.status === "deleted") setMemories((items) => items.filter((candidate) => candidate.memory_id !== item.memory_id));
      else setMemories((items) => items.map((candidate) => candidate.memory_id === item.memory_id ? { ...candidate, content: null, status: "deletion_pending" } : candidate));
      setConfirming(null); setNotice(receipt.status === "deletion_pending" ? "删除请求已接收" : "记忆已删除");
    } catch (nextError) { if (mounted.current) setError(nextError); }
    finally { unlock(lockId); }
  }

  async function refreshDeletion(item: LearningMemory) {
    const receipt = receipts[item.memory_id];
    const lockId = `memory:${item.memory_id}`;
    if (!receipt || !lock(lockId)) return;
    try {
      const nextReceipt = await api.getDeletion(receipt.deletion_id);
      if (!mounted.current) return;
      setReceipts((current) => ({ ...current, [item.memory_id]: nextReceipt }));
      if (nextReceipt.status === "deleted") { setMemories((items) => items.filter((candidate) => candidate.memory_id !== item.memory_id)); setNotice("记忆已删除"); }
      else setNotice("仍在删除处理中");
    } catch (nextError) { if (mounted.current) setError(nextError); }
    finally { unlock(lockId); }
  }

  return (
    <section className="memory-center" aria-labelledby="memory-title">
      <div className="section-heading"><div><p className="section-kicker memory-kicker">本人确认区</p><h2 id="memory-title">个人课程记忆</h2></div><span className="privacy-chip">仅你可见</span></div>
      <p className="privacy-note">系统只能提出建议。只有你接受后，内容才会成为《仓颉语言设计》的长期学习记忆。</p>
      {loading && <p role="status">正在读取你的课程记忆…</p>}
      {error !== null && <RequestState error={error} retry={() => void load()} retryLabel="重试加载记忆" />}
      {notice && <p className="notice" role="status">{notice}</p>}
      {proposals.map((item) => { const busy = busyIds.includes(`proposal:${item.proposal_id}`); return <article className="memory-proposal" key={item.proposal_id}><div><span className="status-badge status-memory">待你确认</span><p>{item.content}</p><small>置信度 {Math.round(item.confidence * 100)}% · 到期 {new Date(item.expires_at).toLocaleDateString("zh-CN")}</small></div><div className="action-row"><button type="button" onClick={() => void accept(item)} disabled={busy}>{busy ? "正在保存…" : "接受记忆建议"}</button><button type="button" className="button-secondary" onClick={() => void reject(item)} disabled={busy}>拒绝记忆建议</button></div></article>; })}
      {!loading && proposals.length === 0 && memories.length === 0 && <p className="empty-copy">还没有经你确认的课程记忆。完成理解验证后，建议会出现在这里。</p>}
      <div className="memory-list">{memories.map((item) => { const busy = busyIds.includes(`memory:${item.memory_id}`); return <article className={`memory-record ${item.status === "deletion_pending" ? "is-pending-delete" : ""}`} key={item.memory_id}>
        {item.status === "deletion_pending" ? <><strong>删除处理中</strong><p>这条记忆已经停止用于学习支持，派生副本正在清理。</p><button type="button" className="button-secondary" onClick={() => void refreshDeletion(item)} disabled={busy || !receipts[item.memory_id]}>刷新删除状态</button></> : <><p>{item.content}</p><small>版本 {item.version} · 私人记忆</small><div className="action-row"><button type="button" className="button-secondary" onClick={() => { setEditing(item.memory_id); setDraft(item.content ?? ""); }} disabled={busy}>纠正记忆</button><button type="button" className="button-danger" aria-expanded={confirming === item.memory_id} aria-controls={`confirm-${item.memory_id}`} disabled={busy} onClick={(event) => { deleteTrigger.current = event.currentTarget; setConfirming(item.memory_id); }}>删除记忆</button></div></>}
        {editing === item.memory_id && <div className="inline-editor"><label htmlFor={`memory-${item.memory_id}`}>纠正后的记忆</label><textarea id={`memory-${item.memory_id}`} value={draft} onChange={(event) => setDraft(event.target.value)} /><div className="action-row"><button type="button" onClick={() => void saveCorrection(item)} disabled={busy}>保存纠正</button><button type="button" className="button-secondary" onClick={() => setEditing(null)} disabled={busy}>取消</button></div></div>}
        {confirming === item.memory_id && <div id={`confirm-${item.memory_id}`} role="dialog" aria-modal="true" aria-label="确认删除个人记忆" className="confirm-panel"><strong>确认删除个人记忆</strong><p>删除开始后，这条记忆会立即停止检索；物理清理可能需要一点时间。</p><div className="action-row"><button ref={confirmButton} type="button" className="button-danger" onClick={() => void confirmDelete(item)} disabled={busy}>确认删除</button><button type="button" className="button-secondary" onClick={closeConfirmation} disabled={busy}>取消</button></div></div>}
      </article>; })}</div>
    </section>
  );
}
