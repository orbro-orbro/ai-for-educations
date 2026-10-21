import { useEffect, useState } from "react";

// Local browser drafts are separate from submitted work and confirmed memory.
export function useCodeDraft(ownerId: string, courseId: string, exerciseId: string, starter: string) {
  const key = ownerId && courseId && exerciseId
    ? `knowbound.code-draft.v1:${JSON.stringify([ownerId, courseId, exerciseId])}` : "";
  const [draft, setDraft] = useState({ key: "", source: starter, status: "尚未保存草稿" });
  useEffect(() => {
    if (!key) return;
    try {
      const saved = localStorage.getItem(key);
      setDraft({ key, source: saved ?? starter, status: saved === null ? "尚未保存草稿" : "草稿已保存到本机，尚未自动提交" });
    } catch {
      setDraft({ key, source: starter, status: "本机保存不可用，请在离开前复制代码" });
    }
  }, [key, starter]);

  function updateSource(source: string) {
    let status = "草稿已保存到本机，尚未自动提交";
    try {
      if (!key) throw new Error("No active draft scope");
      localStorage.setItem(key, source);
    } catch { status = "本机保存失败，请在离开前复制代码"; }
    setDraft({ key, source, status });
  }

  function clearDraft() {
    try {
      localStorage.removeItem(key);
      setDraft({ key, source: starter, status: "本机草稿已清除" });
    } catch { setDraft((current) => ({ ...current, status: "本机清除失败，请检查浏览器存储设置" })); }
  }

  return { source: draft.key === key ? draft.source : starter, updateSource, clearDraft, draftStatus: draft.key === key ? draft.status : "正在读取本机草稿…" };
}
