import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Dashboard from "@/pages/Dashboard";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

vi.mock("@/hooks/useSessionState", () => ({
  useSessionState: () => ({
    data: { source_count: 1, tool_count: 2, skill_count: 0, connector_built: false },
  }),
}));

function renderDashboard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Dashboard />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("Dashboard recent activity", () => {
  it("shows a distinct runtime-unavailable state when the audit fetch fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 503, text: () => Promise.resolve("down") })
    );
    renderDashboard();
    expect(await screen.findByText("Runtime unavailable", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows the idle empty state when the runtime responds with no activity", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve([]) })
    );
    renderDashboard();
    expect(await screen.findByText(/No activity yet/i)).toBeInTheDocument();
  });

  it("renders tool invocations when the audit log has entries", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve([
            { ts: 1716000000, tool_id: "list_animals", result_row_count: 5, duration_ms: 42 },
          ]),
      })
    );
    renderDashboard();
    expect(await screen.findByText("list_animals")).toBeInTheDocument();
  });
});
