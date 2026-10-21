import type { ModelProviderName, ModelProbeStatus, ModelSettingsView } from "./api/client";

export interface ProviderOption {
  value: ModelProviderName;
  label: string;
  remote: boolean;
  modelHint?: string;
  baseUrlHint?: string;
}

export const providerOptions: ProviderOption[] = [
  { value: "environment", label: "跟随部署环境变量（默认）", remote: false },
  { value: "deepseek", label: "DeepSeek", remote: true, modelHint: "deepseek-chat", baseUrlHint: "https://api.deepseek.com" },
  { value: "qwen", label: "千问 Qwen（百炼兼容模式）", remote: true, modelHint: "qwen-plus", baseUrlHint: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { value: "openai_compatible", label: "OpenAI 兼容接口（自定义）", remote: true, modelHint: "服务方给出的模型名", baseUrlHint: "仅限服务端允许的域名，例如 https://api.openai.com/v1" },
  { value: "mock", label: "确定性 Mock（不调用外部模型）", remote: false },
  { value: "disabled", label: "停用模型", remote: false },
];

export const probeMessages: Record<ModelProbeStatus, string> = {
  ok: "连接成功：密钥、模型名与地址都能正常响应。",
  invalid_credentials: "密钥被拒绝，请确认 Key 是否有效、是否有该模型权限。",
  model_or_endpoint_not_found: "地址或模型名不存在，请检查 Base URL 与模型名。",
  rate_limited: "被服务方限流，稍后再试。",
  rejected_request: "请求被服务方拒绝，通常是模型名或参数不受支持。",
  timeout: "连接超时，请检查网络或适当调大超时时间。",
  transport_error: "无法连接到该地址，请检查网络与 Base URL。",
  http_error: "服务方返回异常状态，请稍后重试。",
};

export const sourceLabels: Record<ModelSettingsView["source"], string> = {
  environment: "环境变量",
  web: "本页设置",
};
