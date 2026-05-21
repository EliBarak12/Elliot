import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const callToolFn = vi.fn();
vi.mock("@/lib/mcp-client", () => ({
  callTool: (name: string, args: Record<string, unknown>) => callToolFn(name, args),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { TraceHookPanel } from "@/components/TraceHookPanel";

const STATUS = {
  runtime_url: "http://localhost:3001",
  harnesses: [
    { harness: "claude-code", installed: false, config_path: "/home/u/.claude/settings.json" },
    { harness: "codex", installed: true, config_path: "/home/u/.codex/config.toml" },
    { harness: "cursor", installed: false, config_path: "/home/u/.cursor/hooks.json" },
  ],
};

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TraceHookPanel />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  callToolFn.mockReset();
  callToolFn.mockImplementation((name: string) => {
    if (name === "elliot_trace_hook_status") return Promise.resolve(STATUS);
    return Promise.resolve({ status: "installed" });
  });
});

describe("TraceHookPanel", () => {
  it("lists each supported harness with its install state", async () => {
    renderPanel();
    const rows = await screen.findAllByTestId("trace-hook-row");
    expect(rows).toHaveLength(3);
    expect(screen.getByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Cursor")).toBeInTheDocument();
  });

  it("calls the install tool when an off harness is enabled", async () => {
    renderPanel();
    await screen.findAllByTestId("trace-hook-row");
    // Claude Code is off → its button reads "Install".
    const installButtons = screen.getAllByRole("button", { name: "Install" });
    fireEvent.click(installButtons[0]);
    await waitFor(() =>
      expect(callToolFn).toHaveBeenCalledWith("elliot_install_trace_hook", {
        harness: "claude-code",
      })
    );
  });

  it("calls the uninstall tool for an installed harness", async () => {
    renderPanel();
    await screen.findAllByTestId("trace-hook-row");
    // Codex is installed → its button reads "Remove".
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() =>
      expect(callToolFn).toHaveBeenCalledWith("elliot_uninstall_trace_hook", { harness: "codex" })
    );
  });
});
