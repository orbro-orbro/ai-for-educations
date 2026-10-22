import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useCodeDraft } from "./student/useCodeDraft";

afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });

it("restores drafts separately for each owner, course and exercise", () => {
  const { result, rerender } = renderHook(({owner, course, exercise}) => useCodeDraft(owner, course, exercise, "starter"), {
    initialProps: { owner: "one", course: "course", exercise: "a" },
  });
  act(() => result.current.updateSource("private-a"));
  rerender({ owner: "one", course: "course", exercise: "b" });
  expect(result.current.source).toBe("starter");
  act(() => result.current.updateSource("private-b"));
  rerender({ owner: "two", course: "course", exercise: "a" });
  expect(result.current.source).toBe("starter");
  rerender({ owner: "one", course: "other", exercise: "a" });
  expect(result.current.source).toBe("starter");
  rerender({ owner: "one", course: "course", exercise: "a" });
  expect(result.current.source).toBe("private-a");
  act(() => result.current.clearDraft());
  expect(result.current.source).toBe("starter");
  rerender({ owner: "one", course: "course", exercise: "b" });
  expect(result.current.source).toBe("private-b");
});

it("reports unavailable reads and failed clears without claiming data was removed", () => {
  const read = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("unavailable"); });
  const { result } = renderHook(() => useCodeDraft("one", "course", "a", "starter"));
  expect(result.current.draftStatus).toContain("本机保存不可用");
  read.mockRestore();
  act(() => result.current.updateSource("keep this"));
  vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("unavailable"); });
  act(() => result.current.clearDraft());
  expect(result.current.source).toBe("keep this");
  expect(result.current.draftStatus).toContain("本机清除失败");
});
