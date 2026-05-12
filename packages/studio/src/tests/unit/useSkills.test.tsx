import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";

const callToolMock = vi.fn();
vi.mock("@/lib/mcp-client", () => ({
  callTool: (...args: unknown[]) => callToolMock(...args),
}));

import { useSkills } from "@/hooks/useSkills";

function wrapper(): { Wrapper: (p: { children: ReactNode }) => ReactElement } {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    Wrapper: ({ children }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  };
}

beforeEach(() => {
  callToolMock.mockReset();
});

describe("useSkills (envelope-unwrap regression)", () => {
  it("unwraps {skills:[...], count:N} into a plain array", async () => {
    callToolMock.mockResolvedValueOnce({
      skills: [
        { id: "a", name: "skill_a", description: "", steps: [], input_parameters: [] },
        { id: "b", name: "skill_b", description: "", steps: [], input_parameters: [] },
      ],
      count: 2,
    });
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useSkills(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(Array.isArray(result.current.data)).toBe(true);
    expect(result.current.data).toHaveLength(2);
  });

  it("passes through plain arrays unchanged", async () => {
    callToolMock.mockResolvedValueOnce([{ id: "x", name: "n", steps: [], input_parameters: [] }]);
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useSkills(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
  });

  it("returns [] for unexpected shapes", async () => {
    callToolMock.mockResolvedValueOnce({ something: "else" });
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useSkills(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
