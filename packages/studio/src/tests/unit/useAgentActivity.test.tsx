import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

const sessionData: { value: Record<string, unknown> | null } = { value: null };
const toastSuccess = vi.fn();

vi.mock("sonner", () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args) },
}));

vi.mock("@/hooks/useSessionState", () => ({
  useSessionState: () => ({ data: sessionData.value }),
}));

import { useAgentActivity } from "@/hooks/useAgentActivity";

beforeEach(() => {
  toastSuccess.mockReset();
  sessionData.value = null;
  sessionStorage.clear();
});

describe("useAgentActivity", () => {
  it("does NOT toast on the first session snapshot (baseline)", async () => {
    sessionData.value = { source_count: 0, tool_count: 0, skill_count: 0 };
    const { rerender } = renderHook(() => useAgentActivity());
    rerender();
    await waitFor(() => expect(toastSuccess).not.toHaveBeenCalled());
  });

  it("toasts once per count increase across sources/tools/skills", async () => {
    sessionData.value = { source_count: 0, tool_count: 0, skill_count: 0 };
    const { rerender } = renderHook(() => useAgentActivity());
    // First render establishes baseline. Now bump the counts.
    sessionData.value = { source_count: 1, tool_count: 2, skill_count: 1 };
    rerender();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledTimes(3));
    const messages = toastSuccess.mock.calls.map((c) => c[0] as string);
    expect(messages).toContain("New source added");
    expect(messages).toContain("2 new tools added");
    expect(messages).toContain("New skill added");
  });

  it("toasts when the connector flips from not built to built", async () => {
    sessionData.value = { connector_built: false };
    const { rerender } = renderHook(() => useAgentActivity());
    sessionData.value = { connector_built: true };
    rerender();
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Connector built", expect.anything()));
  });

  it("does not toast when counts decrease (e.g. delete)", async () => {
    sessionData.value = { tool_count: 5 };
    const { rerender } = renderHook(() => useAgentActivity());
    sessionData.value = { tool_count: 3 };
    rerender();
    await waitFor(() => {
      // microtask flush — expect still zero
      expect(toastSuccess).not.toHaveBeenCalled();
    });
  });

  it("isActive flips true briefly after an event", async () => {
    sessionData.value = { tool_count: 0 };
    const { result, rerender } = renderHook(() => useAgentActivity());
    sessionData.value = { tool_count: 1 };
    rerender();
    await waitFor(() => expect(result.current.isActive).toBe(true));
  });
});
