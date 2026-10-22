import { useCallback, useEffect, useState } from "react";

import type {
  ApiClient,
  ModelProviderName,
  PersonalModelSettingsUpdate,
  PersonalModelSettingsView,
} from "../api/client";
import { RequestState } from "../components/RequestState";
import { probeMessages, providerOptions } from "../modelProviders";

const personalProviders = providerOptions.filter((option) => option.remote);
const remoteProviders = new Set(personalProviders.map((option) => option.value));

function draftProvider(view: PersonalModelSettingsView | null): ModelProviderName {
  const current = view?.provider as ModelProviderName | undefined;
  return current && remoteProviders.has(current) ? current : "deepseek";
}

export function StudentModelSettings({ api }: { api: ApiClient }) {
  const [view, setView] = useState<PersonalModelSettingsView | null>(null);
  const [provider, setProvider] = useState<ModelProviderName>("deepseek");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeout, setTimeoutSeconds] = useState("30");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<"load" | "save" | "probe" | "reset" | null>("load");
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const applyView = useCallback((next: PersonalModelSettingsView) => {
    setView(next);
    if (next.scope === "own") {
      setProvider(draftProvider(next));
      setModel(next.model);
      setBaseUrl(next.base_url);
      setTimeoutSeconds(String(next.timeout_seconds));
    }
    setApiKey("");
  }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    setBusy("load");
    setError(null);
    try {
      const next = await api.getMyModelSettings(signal);
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

  const option = personalProviders.find((candidate) => candidate.value === provider) ?? personalProviders[0];
  const locked = view?.environment_locked === true;
  const usingOwn = view?.scope === "own";
  const showForm = usingOwn || editing;

  function payload(mode: "own" | "shared"): PersonalModelSettingsUpdate {
    if (mode === "shared") return { mode };
    return {
      mode: "own",
      provider,
      model: model.trim(),
      base_url: baseUrl.trim(),
      api_key: apiKey.trim(),
      timeout_seconds: Number(timeout) || 30,
    };
  }

  async function save() {
    setBusy("save"); setError(null); setNotice(null);
    try {
      const next = await api.updateMyModelSettings(payload("own"));
      applyView(next);
      setEditing(false);
      setNotice(`已改为 ${next.provider}${next.model ? ` · ${next.model}` : ""}，只影响你自己的诊断与提示。`);
    } catch (nextError) { setError(nextError); }
    finally { setBusy(null); }
  }

  async function probe() {
    setBusy("probe"); setError(null); setNotice(null);
    try {
      const result = await api.probeMyModelSettings(payload("own"));
      setNotice(probeMessages[result.status] ?? "连接结果未知。");
    } catch (nextError) { setError(nextError); }
    finally { setBusy(null); }
  }

  async function useCourseConfiguration() {
    setBusy("reset"); setError(null); setNotice(null);
    try {
      const next = await api.updateMyModelSettings(payload("shared"));
      applyView(next);
      setEditing(false);
      setNotice("已改用老师为本课程配置的模型。");
    } catch (nextError) { setError(nextError); }
    finally { setBusy(null); }
  }

  const effectiveBaseUrl = baseUrl.trim().replace(/\/+$/, "")
    || (["deepseek", "qwen"].includes(provider) ? option.baseUrlHint : "");
  const sameEndpoint = view?.base_url.replace(/\/+$/, "") === effectiveBaseUrl;
  const canReuseKey = usingOwn && view?.personal_configured === true
    && view.provider === provider && sameEndpoint && Boolean(view.key_hint);
  const keyReady = Boolean(apiKey.trim()) || canReuseKey;
  const canSubmit = !locked && Boolean(model.trim()) && keyReady && !busy;

  return (
    <section className="model-settings personal-model-settings" aria-labelledby="my-model-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">MY MODEL</p>
          <h2 id="my-model-title">我的模型接入</h2>
        </div>
        {view && <span className="privacy-chip">{usingOwn ? "使用我的密钥" : "使用老师配置"}</span>}
      </div>

      <p className="privacy-note">
        默认使用老师为本课程配置的模型，不需要额外设置。如果你有自己的 API Key，可以只为自己切换模型：
        密钥只保存在服务端，不会回传浏览器，其他同学和老师都看不到，也不影响别人。
      </p>

      {busy === "load" && <p role="status" className="loading-line">正在读取你的模型设置…</p>}
      {error !== null && <RequestState error={error} retry={() => void load()} retryLabel="重试读取" deniedLabel="无法读取模型设置" />}

      {view && (
        <>
          <dl className="settings-status" aria-label="当前用于你请求的模型">
            <div><dt>当前生效</dt><dd>{view.provider}{view.model ? ` · ${view.model}` : ""}</dd></div>
            <div><dt>来源</dt><dd>{usingOwn ? "我的配置" : "老师配置"}</dd></div>
            <div><dt>老师配置</dt><dd>{view.shared.provider}{view.shared.model ? ` · ${view.shared.model}` : ""}</dd></div>
            <div><dt>我的密钥</dt><dd>{view.personal_configured ? (view.key_hint ?? "已保存") : "未设置"}</dd></div>
          </dl>

          {locked && <div className="notice" role="status">当前部署已锁定模型配置，学生端不可修改。</div>}

          <div className="action-row">
            {usingOwn ? (
              <button type="button" className="button-secondary" disabled={locked || busy !== null} onClick={() => void useCourseConfiguration()}>
                {busy === "reset" ? "正在切换…" : "改用老师的配置"}
              </button>
            ) : (
              <button type="button" className="button-secondary" disabled={locked || busy !== null} onClick={() => { setEditing(true); setNotice(null); }}>
                {editing ? "填写我的 API" : "使用我自己的 API"}
              </button>
            )}
          </div>

          {showForm && (
            <div className="settings-grid">
              <label htmlFor="my-model-provider">接入方式
                <select id="my-model-provider" value={provider} disabled={locked} onChange={(event) => { setProvider(event.target.value as ModelProviderName); setNotice(null); }}>
                  {personalProviders.map((candidate) => <option key={candidate.value} value={candidate.value}>{candidate.label}</option>)}
                </select>
              </label>
              <label htmlFor="my-model-name">模型名
                <input id="my-model-name" value={model} disabled={locked} placeholder={option.modelHint ?? "服务方给出的模型名"} onChange={(event) => setModel(event.target.value)} />
              </label>
              <label htmlFor="my-model-base-url">Base URL
                <input id="my-model-base-url" value={baseUrl} disabled={locked} placeholder={option.baseUrlHint ?? "留空使用官方默认地址"} onChange={(event) => setBaseUrl(event.target.value)} />
              </label>
              <label htmlFor="my-model-api-key">API Key
                <input id="my-model-api-key" type="password" autoComplete="off" value={apiKey} disabled={locked} placeholder={canReuseKey ? `已保存 ${view.key_hint}，留空则保持不变` : "粘贴你自己的密钥"} onChange={(event) => setApiKey(event.target.value)} />
              </label>
              <label htmlFor="my-model-timeout">超时（秒）
                <input id="my-model-timeout" type="number" min={1} max={120} value={timeout} disabled={locked} onChange={(event) => setTimeoutSeconds(event.target.value)} />
              </label>
              <div className="action-row">
                <button type="button" className="button-secondary" disabled={!canSubmit} onClick={() => void probe()}>{busy === "probe" ? "正在测试…" : "测试连接"}</button>
                <button type="button" disabled={!canSubmit} onClick={() => void save()}>{busy === "save" ? "正在保存…" : "保存并启用"}</button>
              </div>
            </div>
          )}

          {notice && <div className="notice is-success" role="status">{notice}</div>}
        </>
      )}
    </section>
  );
}
