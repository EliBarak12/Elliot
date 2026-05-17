import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import MetricsPage from "@/pages/MetricsPage";

vi.mock("@/hooks/useMetrics", () => ({
  useMetrics: () => ({
    data: {
      metrics: [
        { tool_id: "list_animals", call_count: 89, error_rate: 0.02, avg_latency_ms: 43 },
        { tool_id: "get_animal", call_count: 34, error_rate: 0, avg_latency_ms: 21 },
      ],
      days: 30,
    },
    isLoading: false,
  }),
}));

const EFFICIENCY_RESPONSE = {
  tools: [
    {
      tool_id: "list_all",
      call_count: 47,
      avg_tokens: 1420,
      max_tokens: 4100,
      avg_duration_ms: 110,
      error_count: 0,
      risk: "high" as const,
      suggestion: "Average 1420 tokens is very high. Add LIMIT clause or SELECT only needed columns.",
    },
    {
      tool_id: "list_animals",
      call_count: 89,
      avg_tokens: 87,
      max_tokens: 230,
      avg_duration_ms: 43,
      error_count: 2,
      risk: "low" as const,
      suggestion: null,
    },
  ],
  sessions_analysed: 10,
};

const HARNESS_RESPONSE = {
  harnesses: [
    { harness: "claude-code", sessions: 3, tool_calls: 12, errors: 1, tokens: 540, avg_duration_ms: 40 },
    { harness: "cursor", sessions: 1, tool_calls: 4, errors: 0, tokens: 90, avg_duration_ms: 22 },
  ],
};

function renderPage() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(
            String(url).includes("/harnesses") ? HARNESS_RESPONSE : EFFICIENCY_RESPONSE
          ),
      })
    )
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MetricsPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("MetricsPage token efficiency", () => {
  it("renders stats cards from metrics data", async () => {
    renderPage();
    expect(screen.getByText("Total calls")).toBeInTheDocument();
    expect(screen.getByText("123")).toBeInTheDocument(); // 89 + 34
  });

  it("renders token efficiency table after fetch", async () => {
    renderPage();
    expect(await screen.findByText("Token efficiency")).toBeInTheDocument();
    expect(screen.getByText("list_all")).toBeInTheDocument();
  });

  it("shows high risk badge for expensive tool", async () => {
    renderPage();
    const badge = await screen.findByText("high");
    expect(badge).toBeInTheDocument();
  });

  it("shows low risk badge for cheap tool", async () => {
    renderPage();
    await screen.findByText("Token efficiency");
    expect(screen.getByText("low")).toBeInTheDocument();
  });

  it("shows suggestion text for high-risk tool", async () => {
    renderPage();
    expect(
      await screen.findByText(/Average 1420 tokens is very high/i)
    ).toBeInTheDocument();
  });

  it("shows em-dash for tool with no suggestion", async () => {
    renderPage();
    await screen.findByText("Token efficiency");
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  it("renders the per-harness breakdown", async () => {
    renderPage();
    expect(await screen.findByText("By agent harness")).toBeInTheDocument();
    expect(screen.getByText("claude-code")).toBeInTheDocument();
    expect(screen.getByText("cursor")).toBeInTheDocument();
    const rows = screen.getAllByTestId("harness-row");
    expect(rows).toHaveLength(2);
  });
});
