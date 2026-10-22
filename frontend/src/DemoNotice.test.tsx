import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DemoNotice } from "./DemoNotice";

describe("DemoNotice", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
  });

  it("renders nothing outside the synthetic demo", () => {
    vi.stubEnv("VITE_SYNTHETIC_DEMO", "false");
    const { container } = render(<DemoNotice />);
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps the deterministic Mock disclaimer when no live model is configured", () => {
    vi.stubEnv("VITE_SYNTHETIC_DEMO", "true");
    vi.stubEnv("VITE_MODEL_LABEL", "");
    render(<DemoNotice />);
    expect(screen.getByRole("note")).toHaveTextContent("模型响应为确定性 Mock");
    expect(screen.getByRole("note")).toHaveTextContent("非教学试点结果");
  });

  it("separates synthetic data from the real live model and never claims Mock", () => {
    vi.stubEnv("VITE_SYNTHETIC_DEMO", "true");
    vi.stubEnv("VITE_MODEL_LABEL", "DeepSeek · deepseek-test");
    render(<DemoNotice />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("数据为合成演示数据");
    expect(note).toHaveTextContent("模型为真实调用：DeepSeek · deepseek-test");
    expect(note).toHaveTextContent("非教学试点结果");
    expect(note).not.toHaveTextContent("确定性 Mock");
  });
});
