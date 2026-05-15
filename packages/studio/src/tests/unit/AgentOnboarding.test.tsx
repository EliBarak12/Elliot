import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AgentOnboarding } from "@/components/dashboard/AgentOnboarding";

function installClipboardSpy() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  return writeText;
}

describe("AgentOnboarding", () => {
  it("shows `make dev` as the default install path (the one that actually works today)", () => {
    render(<AgentOnboarding />);
    expect(screen.getByText(/Let your agent do the work/i)).toBeInTheDocument();
    expect(screen.getByText(/\$ make dev/)).toBeInTheDocument();
    expect(
      screen.getByText(/I have an API at https:\/\/api.example.com/i)
    ).toBeInTheDocument();
  });

  it("offers install commands for every supported agent surface", () => {
    render(<AgentOnboarding />);
    for (const label of [
      "Local dev (this repo)",
      "Claude Code marketplace",
      "Codex marketplace",
      "Cursor, VS Code, Windsurf",
    ]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("switches to the Claude Code marketplace commands when its tab is selected", () => {
    render(<AgentOnboarding />);
    fireEvent.click(screen.getByRole("button", { name: "Claude Code marketplace" }));
    expect(
      screen.getByText(/\$ \/plugin marketplace add EliBarak12\/elliot/)
    ).toBeInTheDocument();
    expect(screen.getByText(/\$ \/plugin install elliot@elliot/)).toBeInTheDocument();
  });

  it("switches to the Codex install commands when its tab is selected", () => {
    render(<AgentOnboarding />);
    fireEvent.click(screen.getByRole("button", { name: "Codex marketplace" }));
    expect(
      screen.getByText(/\$ codex plugin marketplace add EliBarak12\/elliot/)
    ).toBeInTheDocument();
    expect(screen.getByText(/\$ \/plugin install elliot/)).toBeInTheDocument();
  });

  it("switches to the npx auto-install command when the cross-agent tab is selected", () => {
    render(<AgentOnboarding />);
    fireEvent.click(screen.getByRole("button", { name: "Cursor, VS Code, Windsurf" }));
    expect(screen.getByText(/\$ npx @elliot\/connect/)).toBeInTheDocument();
  });

  it("copies a marketplace command to clipboard when its copy button is clicked", async () => {
    const writeText = installClipboardSpy();
    render(<AgentOnboarding />);
    fireEvent.click(screen.getByRole("button", { name: "Claude Code marketplace" }));
    fireEvent.click(
      screen.getByLabelText(/Copy command: \/plugin marketplace add EliBarak12\/elliot/i)
    );
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith("/plugin marketplace add EliBarak12/elliot")
    );
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
    expect(
      screen.queryByText(/Tell your agent what to build/i)
    ).not.toBeInTheDocument();
    expect(screen.getByText(/\$ \/plugin install elliot@elliot/)).toBeInTheDocument();
  });
});
