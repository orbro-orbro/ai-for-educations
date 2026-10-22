import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiClient } from "./api/client";
import { StudentModelSettings } from "./student/StudentModelSettings";

const apiBaseUrl = "http://localhost:8199";
const sharedView = {
  scope: "shared",
  provider: "deepseek",
  model: "deepseek-chat",
  base_url: "https://api.deepseek.com",
  source: "web",
  configured: true,
  key_hint: null,
  timeout_seconds: 30,
  personal_configured: false,
  shared: { provider: "deepseek", model: "deepseek-chat", configured: true },
  persistence: "file",
  environment_locked: false,
};
const ownView = {
  ...sharedView,
  scope: "own",
  key_hint: "****2222",
  personal_configured: true,
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
  render(<StudentModelSettings api={new ApiClient(apiBaseUrl, () => "student-token")} />);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("student model settings", () => {
  it("starts on the teacher configuration without asking for a key", async () => {
    renderPanel((url) => (url.pathname === "/model-settings" ? json(sharedView) : undefined));

    expect(await screen.findByText("使用老师配置")).toBeInTheDocument();
    expect(screen.getByText("当前生效")).toBeInTheDocument();
    expect(screen.getAllByText("deepseek · deepseek-chat").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument();
  });

  it("saves a personal provider and reports it as personal", async () => {
    const saved: Array<Record<string, unknown>> = [];
    renderPanel((url, init) => {
      if (url.pathname === "/model-settings" && init.method === "PUT") {
        saved.push(JSON.parse(String(init.body)));
        return json(ownView);
      }
      if (url.pathname === "/model-settings") return json(sharedView);
      return undefined;
    });

    fireEvent.click(await screen.findByRole("button", { name: "使用我自己的 API" }));
    fireEvent.change(screen.getByLabelText("模型名"), { target: { value: "deepseek-chat" } });
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-personal" } });
    fireEvent.click(screen.getByRole("button", { name: "保存并启用" }));

    await waitFor(() => expect(screen.getByText("使用我的密钥")).toBeInTheDocument());
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({
      mode: "own",
      provider: "deepseek",
      model: "deepseek-chat",
      api_key: "sk-personal",
    });
  });

  it("switches back to the teacher configuration", async () => {
    const saved: Array<Record<string, unknown>> = [];
    renderPanel((url, init) => {
      if (url.pathname === "/model-settings" && init.method === "PUT") {
        saved.push(JSON.parse(String(init.body)));
        return json(sharedView);
      }
      if (url.pathname === "/model-settings") return json(ownView);
      return undefined;
    });

    fireEvent.click(await screen.findByRole("button", { name: "改用老师的配置" }));

    await waitFor(() => expect(screen.getByText("使用老师配置")).toBeInTheDocument());
    expect(saved[0]).toEqual({ mode: "shared" });
  });

  it("keeps the panel read-only in production", async () => {
    renderPanel((url) =>
      url.pathname === "/model-settings" ? json({ ...sharedView, environment_locked: true }) : undefined
    );

    expect(await screen.findByRole("button", { name: "使用我自己的 API" })).toBeDisabled();
    expect(screen.getByText(/当前部署已锁定/)).toBeInTheDocument();
  });
  it("requires an explicit key when changing the endpoint", async () => {
    renderPanel((url) => url.pathname === "/model-settings" ? json(ownView) : undefined);
    fireEvent.change(await screen.findByLabelText("Base URL"), { target: { value: "https://other.example/v1" } });
    expect(screen.getByRole("button", { name: "保存并启用" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "测试连接" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "new-explicit-key" } });
    expect(screen.getByRole("button", { name: "保存并启用" })).not.toBeDisabled();
  });

});
