import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("identifies the product and its two supported roles", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "知界·仓颉学伴" })).toBeInTheDocument();
    expect(screen.getByText("学生端")).toBeInTheDocument();
    expect(screen.getByText("教师端")).toBeInTheDocument();
    expect(screen.queryByText("助教端")).not.toBeInTheDocument();
  });

  it("uses the server-verified role returned by login", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      if (path === "/auth/login") return new Response(JSON.stringify({ access_token: "student-token", token_type: "bearer", actor: { user_id: "student-1", role: "student" } }), { status: 200, headers: { "Content-Type": "application/json" } });
      if (path === "/courses") return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "student" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("学生工作台")).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem("knowbound.session") ?? "{}")).toMatchObject({ actor: { role: "student" } });
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("http://localhost:8000/auth/login");
  });
});
