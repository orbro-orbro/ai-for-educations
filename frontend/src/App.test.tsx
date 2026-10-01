import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";

describe("App", () => {
  it("identifies the product and its two supported roles", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "知界·仓颉学伴" })).toBeInTheDocument();
    expect(screen.getByText("学生端")).toBeInTheDocument();
    expect(screen.getByText("教师端")).toBeInTheDocument();
    expect(screen.queryByText("助教端")).not.toBeInTheDocument();
  });
});
