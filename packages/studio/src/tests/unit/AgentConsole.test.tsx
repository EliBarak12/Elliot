import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AgentConsole from "@/pages/AgentConsole";

const SESSION_OK = {
  session_id: "a3f9b1c2",
  started_at: 1700000000,
  agent_hint: "claude-code",
  events: [
    {
      ts: 1700000001,
      type: "tool_call",
      tool_id: "list_animals",
      arguments: { species: "dog" },
      result_rows: 3,
      result_token_estimate: 87,
      duration_ms: 43,
      error: null,
    },
  ],
  total_tool_calls: 1,
  total_tokens_estimated: 87,
  total_duration_ms: 43,
  error_count: 0,
};

const SESSION_LARGE = {
  session_id: "f7a2e001",
  started_at: 1700000100,
  agent_hint: "claude-code",
  events: [
    {
      ts: 1700000101,
      type: "tool_call",
      tool_id: "list_all",
      arguments: {},
      result_rows: 94,
      result_token_estimate: 1823,
      duration_ms: 210,
      error: null,
    },
  ],
  total_tool_calls: 1,
  total_tokens_estimated: 1823,
  total_duration_ms: 210,
  error_count: 0,
};

function renderConsole(sessions: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(sessions),
    })
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AgentConsole />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("AgentConsole", () => {
  it("renders session rows", async () => {
    renderConsole([SESSION_OK, SESSION_LARGE]);
    const rows = await screen.findAllByTestId("session-row");
    expect(rows).toHaveLength(2);
  });

  it("shows session id and agent hint", async () => {
    renderConsole([SESSION_OK]);
    await screen.findByTestId("session-row");
    expect(screen.getByText("a3f9b1c2")).toBeInTheDocument();
    expect(screen.getByText("claude-code")).toBeInTheDocument();
  });

  it("expands session on click to show event rows", async () => {
    renderConsole([SESSION_OK]);
    const row = await screen.findByTestId("session-row");
    fireEvent.click(row);
    expect(screen.getByText("list_animals")).toBeInTheDocument();
  });

  it("shows large result warning banner", async () => {
    renderConsole([SESSION_LARGE]);
    await screen.findByTestId("session-row");
    expect(screen.getByText(/Consider adding LIMIT/i)).toBeInTheDocument();
  });

  it("shows empty state when no sessions", async () => {
    renderConsole([]);
    expect(
      await screen.findByText(/No agent sessions yet/i)
    ).toBeInTheDocument();
  });
});
