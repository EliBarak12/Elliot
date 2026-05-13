import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AgentOnboarding } from "@/components/dashboard/AgentOnboarding";

function installClipboardSpy() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  // Reinstall on every test — jsdom doesn't ship clipboard, and
  // @testing-library/user-event's setup() can shadow it. fireEvent
  // doesn't, so we stay in control of the spy.
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  return writeText;
}

describe("AgentOnboarding", () => {
  it("shows the make dev command and the example prompt by default", () => {
    render(<AgentOnboarding />);
    expect(screen.getByText(/Let your agent do the work/i)).toBeInTheDocument();
    expect(screen.getByText(/\$ make dev/)).toBeInTheDocument();
    expect(
      screen.getByText(/I have an API at https:\/\/api.example.com/i)
    ).toBeInTheDocument();
  });

  it("lists every auto-registered agent so the user knows it's covered", () => {
    render(<AgentOnboarding />);
    for (const agent of [
      "Claude Code",
      "Cursor",
      "VS Code / Copilot",
      "Windsurf",
      "Codex",
    ]) {
      expect(screen.getByText(agent)).toBeInTheDocument();
    }
  });

  it("copies the command to clipboard when the copy button is clicked", async () => {
    const writeText = installClipboardSpy();
    render(<AgentOnboarding />);
    fireEvent.click(screen.getByLabelText(/Copy command: make dev/i));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("make dev"));
  });

  it("copies the example prompt to clipboard", async () => {
    const writeText = installClipboardSpy();
    render(<AgentOnboarding />);
    fireEvent.click(screen.getByLabelText(/Copy example prompt/i));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        expect.stringContaining("https://api.example.com")
      )
    );
  });

  it("renders the compact reconnect hint when the agent has already produced output", () => {
    render(<AgentOnboarding compact />);
    expect(screen.getByText(/Your agent runs the show/i)).toBeInTheDocument();
    // The full three-step walkthrough is not present in compact mode.
    expect(screen.queryByText(/Tell your agent what to build/i)).not.toBeInTheDocument();
    // But the reconnect command is still copyable.
    expect(screen.getByText(/\$ make dev/)).toBeInTheDocument();
  });
});
