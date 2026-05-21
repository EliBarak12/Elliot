import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FeedbackPanel } from "@/components/FeedbackPanel";

const FEEDBACK_SUCCESS = {
  id: 1,
  session_id: "s1",
  ts: 1700000000,
  connector_slug: "pets",
  tool_id: "list_animals",
  outcome: "success",
  why_chosen: "It returns every animal in one call",
  input_summary: "species=dog",
  output_summary: "3 rows returned",
  detail: "worked first try",
  agent_client: "claude-code",
  agent_model: "claude-opus-4-7",
};

const FEEDBACK_FAILURE = {
  id: 2,
  session_id: "s2",
  ts: 1700000100,
  connector_slug: "pets",
  tool_id: "delete_animal",
  outcome: "failure",
  why_chosen: null,
  input_summary: "id=99",
  output_summary: null,
  detail: "404 — animal not found",
  agent_client: "cursor",
  agent_model: null,
};

function renderPanel(feedback: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ feedback }),
    })
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FeedbackPanel />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("FeedbackPanel", () => {
  it("renders a feedback row per item", async () => {
    renderPanel([FEEDBACK_SUCCESS, FEEDBACK_FAILURE]);
    const rows = await screen.findAllByTestId("feedback-row");
    expect(rows).toHaveLength(2);
  });

  it("shows tool id, outcome and agent identity", async () => {
    renderPanel([FEEDBACK_SUCCESS]);
    await screen.findByTestId("feedback-row");
    expect(screen.getByText("list_animals")).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
    expect(screen.getByText("claude-code/claude-opus-4-7")).toBeInTheDocument();
  });

  it("expands a row to show the agent's reasoning, input, output and detail", async () => {
    renderPanel([FEEDBACK_SUCCESS]);
    const row = await screen.findByTestId("feedback-row");
    fireEvent.click(row);
    expect(screen.getByText("Why this tool")).toBeInTheDocument();
    expect(screen.getByText(/returns every animal/)).toBeInTheDocument();
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByText("Output")).toBeInTheDocument();
    expect(screen.getByText("Detail / notes")).toBeInTheDocument();
  });

  it("shows the empty state when there is no feedback", async () => {
    renderPanel([]);
    expect(await screen.findByText(/No agent feedback yet/i)).toBeInTheDocument();
  });
});
