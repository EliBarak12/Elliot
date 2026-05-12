import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement, ReactNode } from "react";

const callToolMock = vi.fn();
vi.mock("@/lib/mcp-client", () => ({
  callTool: (...args: unknown[]) => callToolMock(...args),
}));

import { useSources } from "@/hooks/useSources";

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

describe("useSources (Bug #7 regression)", () => {
  it("unwraps {sources:[...], count:N} envelope into a plain array", async () => {
    callToolMock.mockResolvedValueOnce({
      sources: [
        { id: "a", name: "customers", type: "file" },
        { id: "b", name: "events", type: "file" },
      ],
      count: 2,
    });
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useSources(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(Array.isArray(result.current.data)).toBe(true);
    expect(result.current.data).toHaveLength(2);
    expect((result.current.data as Array<{ name: string }>)[0].name).toBe("customers");
  });

  it("passes through plain arrays unchanged", async () => {
    callToolMock.mockResolvedValueOnce([{ id: "x", name: "n", type: "file" }]);
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useSources(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(Array.isArray(result.current.data)).toBe(true);
    expect(result.current.data).toHaveLength(1);
  });

  it("returns an empty array for unexpected shapes", async () => {
    callToolMock.mockResolvedValueOnce({ something: "else" });
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useSources(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([]);
  });
});
