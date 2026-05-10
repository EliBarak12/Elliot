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

function renderPage() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(EFFICIENCY_RESPONSE),
    })
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
});
