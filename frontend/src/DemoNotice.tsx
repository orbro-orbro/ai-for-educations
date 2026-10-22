export function DemoNotice() {
  if (import.meta.env.VITE_SYNTHETIC_DEMO !== "true") return null;
  const modelLabel = (import.meta.env.VITE_MODEL_LABEL ?? "").trim();
  if (!modelLabel) {
    return <p role="note">比赛合成演示 · 模型响应为确定性 Mock · 编译反馈来自真实隔离 Runner · 非教学试点结果</p>;
  }
  return <p role="note">比赛合成演示 · 数据为合成演示数据 · 模型为真实调用：{modelLabel} · 编译反馈来自真实隔离 Runner · 非教学试点结果</p>;
}
