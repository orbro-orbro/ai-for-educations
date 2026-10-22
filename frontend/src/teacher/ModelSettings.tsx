import { useCallback, useEffect, useState } from "react";

import type {
  ApiClient,
  ModelProviderName,
  ModelSettingsUpdate,
  ModelSettingsView,
} from "../api/client";
import { RequestState } from "../components/RequestState";
import { probeMessages, providerOptions, sourceLabels } from "../modelProviders";

function draftFrom(view: ModelSettingsView) {
  const known = providerOptions.some((option) => option.value === view.provider);
  const provider: ModelProviderName = known ? (view.provider as ModelProviderName) : "environment";
  return {
    provider,
    model: view.model,
    baseUrl: view.base_url,
    apiKey: "",
    timeout: String(view.timeout_seconds),
  };
}

export function ModelSettings({ api }: { api: ApiClient }) {
  const [view, setView] = useState<ModelSettingsView | null>(null);
  const [provider, setProvider] = useState<ModelProviderName>("environment");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeout, setTimeoutSeconds] = useState("30");
  const [busy, setBusy] = useState<"load" | "save" | "probe" | null>("load");
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const applyView = useCallback((next: ModelSettingsView) => {
    setView(next);
    const draft = draftFrom(next);
    setProvider(draft.provider);
    setModel(draft.model);
    setBaseUrl(draft.baseUrl);
    setTimeoutSeconds(draft.timeout);
    setApiKey("");
  }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy("load");
    setError(null);
    try {
      const next = await api.getModelSettings(signal);
      if (!signal?.aborted) applyView(next);
    } catch (nextError) {
      if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError);
    } finally {
      if (!signal?.aborted) setBusy(null);
    }
  }, [api, applyView]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const option = providerOptions.find((candidate) => candidate.value === provider) ?? providerOptions[0];
  const locked = view?.environment_locked === true;

  function payload(): ModelSettingsUpdate {
    if (!option.remote) {
      return { provider, model: "", base_url: "", api_key: "", timeout_seconds: Number(timeout) || 30 };
    }
    return {
      provider,
      model: model.trim(),
      base_url: baseUrl.trim(),
      api_key: apiKey.trim(),
      timeout_seconds: Number(timeout) || 30,
    };
  }

  async function save() {
    setBusy("save");
    setError(null);
    setNotice(null);
    try {
      const next = await api.updateModelSettings(payload());
      applyView(next);
      setNotice(`已切换为 ${next.provider}${next.model ? ` · ${next.model}` : ""}，下一次诊断请求即刻生效。`);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(null);
    }
  }

  async function probe() {
    setBusy("probe");
    setError(null);
    setNotice(null);
    try {
      const result = await api.probeModelSettings(payload());
      setNotice(probeMessages[result.status] ?? "连接结果未知。");
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(null);
    }
  }

  const effectiveBaseUrl = baseUrl.trim().replace(/\/+$/, "")
    || (["deepseek", "qwen"].includes(provider) ? option.baseUrlHint : "");
  const sameEndpoint = view?.base_url.replace(/\/+$/, "") === effectiveBaseUrl;
  const canReuseKey = view?.configured === true && view.provider === provider && sameEndpoint;
  const keyReady = Boolean(apiKey.trim()) || canReuseKey;
  const canSubmit = !locked
    && (option.remote ? Boolean(model.trim()) && keyReady : true)
    && !busy;

  // The banner above the page is built from MODEL_LABEL at image build time. A
  // runtime switch can make that claim stale, and this project never lets a UI
  // misstate which model answered.
  const buildLabel = (import.meta.env.VITE_MODEL_LABEL ?? "").trim();
  const bannerAgrees = view === null
    ? true
    : view.provider === "mock" || view.provider === "disabled"
      ? buildLabel.length === 0
      : buildLabel.length > 0 && Boolean(view.model) && buildLabel.includes(view.model);

  return (
    <section className="model-settings" aria-labelledby="model-settings-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">MODEL PROVIDER</p>
          <h2 id="model-settings-title">模型接入</h2>
        </div>
        {view && <span className="privacy-chip">{view.configured ? "已配置密钥" : "未配置密钥"}</span>}
      </div>

      <p className="privacy-note">
        密钥只写入本机 API 容器，不会回传浏览器，也不进入日志与审计记录。改动对下一次诊断请求生效，无需重启。
      </p>

      {busy === "load" && <p role="status" className="loading-line">正在读取当前模型配置…</p>}
      {error !== null && <RequestState error={error} retry={() => void load()} retryLabel="重试读取配置" deniedLabel="无法访问模型配置" />}

      {view && (
        <>
          <dl className="settings-status" aria-label="当前生效的模型配置">
            <div><dt>接入方式</dt><dd>{view.provider}</dd></div>
            <div><dt>模型</dt><dd>{view.model || "—"}</dd></div>
            <div><dt>密钥</dt><dd>{view.key_hint ?? "未配置"}</dd></div>
            <div><dt>配置来源</dt><dd>{sourceLabels[view.source]}</dd></div>
          </dl>

          {locked && <div className="notice" role="status">当前部署已锁定模型配置；固定 Mock 演示、生产环境或未启用网页配置时只读。</div>}

          <div className="settings-grid">
            <label htmlFor="model-provider">接入方式
              <select id="model-provider" value={provider} disabled={locked} onChange={(event) => { setProvider(event.target.value as ModelProviderName); setNotice(null); }}>
                {providerOptions.map((candidate) => <option key={candidate.value} value={candidate.value}>{candidate.label}</option>)}
              </select>
            </label>
            <label htmlFor="model-name">模型名
              <input id="model-name" value={model} disabled={locked || !option.remote} placeholder={option.modelHint ?? "先选择接入方式"} onChange={(event) => setModel(event.target.value)} />
            </label>
            <label htmlFor="model-base-url">Base URL
              <input id="model-base-url" value={baseUrl} disabled={locked || !option.remote} placeholder={option.baseUrlHint ?? "留空使用官方默认地址"} onChange={(event) => setBaseUrl(event.target.value)} />
            </label>
            <label htmlFor="model-api-key">API Key
              <input id="model-api-key" type="password" autoComplete="off" value={apiKey} disabled={locked || !option.remote} placeholder={view.key_hint ? `已保存 ${view.key_hint}，留空则保持不变` : "粘贴密钥"} onChange={(event) => setApiKey(event.target.value)} />
            </label>
            <label htmlFor="model-timeout">超时（秒）
              <input id="model-timeout" type="number" min={1} max={120} value={timeout} disabled={locked} onChange={(event) => setTimeoutSeconds(event.target.value)} />
            </label>
            <div className="action-row">
              <button type="button" className="button-secondary" disabled={!canSubmit || !option.remote} onClick={() => void probe()}>{busy === "probe" ? "正在测试…" : "测试连接"}</button>
              <button type="button" disabled={!canSubmit} onClick={() => void save()}>{busy === "save" ? "正在保存…" : "保存并启用"}</button>
            </div>
          </div>

          {notice && <div className="notice is-success" role="status">{notice}</div>}
          {!bannerAgrees && <div className="notice" role="status">
            页面顶部横幅的模型声明来自构建时标签（{buildLabel || "未设置，按 Mock 声明"}），与当前生效配置不一致。答辩或截图时请以本面板为准，或按当前模型重新构建前端。
          </div>}
          <p className="privacy-note">
            {view.persistence === "file"
              ? "配置保存在本机数据卷，重启容器后仍然生效。"
              : "本次运行有效：重启 API 进程后回到环境变量配置。"}
            {" "}同一接入方式及地址下留空密钥会沿用已保存的密钥；更换地址须重新填写密钥；要回到部署配置请选择「跟随部署环境变量」。
          </p>
        </>
      )}
    </section>
  );
}
