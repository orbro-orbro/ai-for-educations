import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClient } from "./api/client";
import { ModelSettings } from "./teacher/ModelSettings";

const apiBaseUrl = "http://localhost:8198";
const configuredView = {
  provider: "deepseek",
  model: "deepseek-chat",
  base_url: "https://api.deepseek.com",
  source: "web",
  configured: true,
  key_hint: "****9876",
  timeout_seconds: 30,
  persistence: "file",
  environment_locked: false,
};
const disabledView = {
  provider: "disabled",
  model: "",
  base_url: "",
  source: "environment",
  configured: false,
  key_hint: null,
  timeout_seconds: 30,
  persistence: "file",
  environment_locked: false,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderPanel(handler: (url: URL, init: RequestInit) => Response | undefined) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const response = handler(new URL(String(input)), init);
    if (response) return response;
    throw new Error(`Unexpected request: ${init.method ?? "GET"} ${String(input)}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<ModelSettings api={new ApiClient(apiBaseUrl, () => "teacher-token")} />);
  return fetchMock;
}

function selectProvider(value: string) {
  fireEvent.change(screen.getByRole("combobox", { name: "接入方式" }), { target: { value } });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("teacher model settings", () => {
  it("shows the effective configuration with only a key hint", async () => {
    renderPanel((url) => (url.pathname === "/teacher/model-settings" ? json(configuredView) : undefined));

    expect(await screen.findByText("****9876")).toBeInTheDocument();
    expect(screen.getByText("本页设置")).toBeInTheDocument();
    const keyInput = screen.getByLabelText("API Key") as HTMLInputElement;
    expect(keyInput.type).toBe("password");
    expect(keyInput.value).toBe("");
  });

  it("saves a new provider from the page and confirms it", async () => {
    const saved: Array<Record<string, unknown>> = [];
    const fetchMock = renderPanel((url, init) => {
      if (url.pathname === "/teacher/model-settings" && init.method === "PUT") {
        saved.push(JSON.parse(String(init.body)));
        return json(configuredView);
      }
      if (url.pathname === "/teacher/model-settings") return json(disabledView);
      return undefined;
    });

    await screen.findByLabelText("接入方式");
    selectProvider("deepseek");
    fireEvent.change(screen.getByLabelText("模型名"), { target: { value: "deepseek-chat" } });
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-browser-sentinel" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并启用" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0]).toMatchObject({ provider: "deepseek", model: "deepseek-chat", api_key: "sk-browser-sentinel" });
    expect(await screen.findByText(/已切换为 deepseek/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

  it("keeps the stored key usable when only the model name changes", async () => {
    renderPanel((url) => (url.pathname === "/teacher/model-settings" ? json(configuredView) : undefined));

    await screen.findByLabelText("模型名");
    const save = screen.getByRole("button", { name: "保存并启用" });
    expect(save).toBeEnabled();
    expect((screen.getByLabelText("API Key") as HTMLInputElement).placeholder).toContain("****9876");
  });

  it("reports a rejected key from the connection test", async () => {
    renderPanel((url) => {
      if (url.pathname === "/teacher/model-settings/probe") return json({ status: "invalid_credentials", http_status: 401 });
      if (url.pathname === "/teacher/model-settings") return json(configuredView);
      return undefined;
    });

    await screen.findByLabelText("模型名");
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText(/密钥被拒绝/)).toBeInTheDocument();
  });

  it("warns when the build-time banner label no longer matches the active model", async () => {
    renderPanel((url) => (url.pathname === "/teacher/model-settings" ? json(configuredView) : undefined));

    await screen.findByLabelText("模型名");
    expect(screen.getByText(/与当前生效配置不一致/)).toBeInTheDocument();
  });

  it("is read-only when the deployment owns the configuration", async () => {
    renderPanel((url) => (url.pathname === "/teacher/model-settings" ? json({ ...configuredView, environment_locked: true }) : undefined));

    await screen.findByLabelText("接入方式");
    expect(screen.getByRole("combobox", { name: "接入方式" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存并启用" })).toBeDisabled();
    expect(screen.getByText(/当前部署已锁定/)).toBeInTheDocument();
  });
  it("requires an explicit key when changing the endpoint", async () => {
    renderPanel((url) => url.pathname === "/teacher/model-settings" ? json(configuredView) : undefined);
    fireEvent.change(await screen.findByLabelText("Base URL"), { target: { value: "https://other.example/v1" } });
    expect(screen.getByRole("button", { name: "保存并启用" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "测试连接" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "new-explicit-key" } });
    expect(screen.getByRole("button", { name: "保存并启用" })).not.toBeDisabled();
  });

});
