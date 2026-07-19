import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const navigateFn = vi.fn();
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
  useNavigate: () => navigateFn,
}));

const callToolFn = vi.fn();
let toolsData: unknown = [
  {
    id: "get_customer_overview",
    name: "Get Customer Overview",
    description: "Return one customer's full picture",
    category: "READ",
    parameters: [],
  },
];
vi.mock("@/hooks/useTools", () => ({
  useTools: () => ({ data: toolsData }),
  useCallTool: () => ({
    mutateAsync: (input: unknown) => callToolFn(input),
    isPending: false,
  }),
}));

// AgentOnboarding pulls in icon assets and clipboard plumbing that are
// irrelevant here — the welcome page only needs to *mount* it as step 3.
vi.mock("@/components/dashboard/AgentOnboarding", () => ({
  AgentOnboarding: () => <div data-testid="agent-onboarding" />,
}));

import WelcomePage, { WELCOME_DISMISSED_KEY } from "@/pages/WelcomePage";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
});

describe("WelcomePage", () => {
  it("renders the three tour steps", () => {
    render(<WelcomePage />);
    expect(screen.getByText("Run a tool")).toBeInTheDocument();
    expect(screen.getByText("See the trace")).toBeInTheDocument();
    expect(screen.getByText("Connect your agent")).toBeInTheDocument();
    expect(screen.getByTestId("agent-onboarding")).toBeInTheDocument();
  });

  it("runs the demo tool and shows the result with its token estimate", async () => {
    callToolFn.mockResolvedValue({
      rows: [{ id: 1, name: "Alice Chen", total_events: 3 }],
      meta: { token_estimate: 42 },
    });
    render(<WelcomePage />);
    await userEvent.click(screen.getByRole("button", { name: /run get_customer_overview/i }));
    await waitFor(() => {
      expect(screen.getByText(/~42 tokens/)).toBeInTheDocument();
    });
    expect(callToolFn).toHaveBeenCalledWith({
      name: "get_customer_overview",
      args: { customer_id: 1 },
    });
    expect(screen.getByText(/Alice Chen/)).toBeInTheDocument();
  });

  it("surfaces a failed call as an alert, not a crash", async () => {
    callToolFn.mockRejectedValue(new Error("VALIDATION_MISSING_PARAM: customer_id"));
    render(<WelcomePage />);
    await userEvent.click(screen.getByRole("button", { name: /run get_customer_overview/i }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/VALIDATION_MISSING_PARAM/);
    });
  });

  it("skip persists the dismissal and navigates home", async () => {
    render(<WelcomePage />);
    await userEvent.click(screen.getByRole("button", { name: /skip the tour/i }));
    expect(localStorage.getItem(WELCOME_DISMISSED_KEY)).toBe("true");
    expect(navigateFn).toHaveBeenCalledWith({ to: "/" });
  });

  it("falls back to the connector editor when no tools are loaded", () => {
    toolsData = [];
    render(<WelcomePage />);
    expect(screen.getByText(/no tools are loaded yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open the connector editor/i })).toHaveAttribute(
      "href",
      "/connector",
    );
    toolsData = [
      {
        id: "get_customer_overview",
        name: "Get Customer Overview",
        description: "Return one customer's full picture",
        category: "READ",
        parameters: [],
      },
    ];
  });
});
