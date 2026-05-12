import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ToolEditor } from "@/components/tools/ToolEditor";

vi.mock("@/lib/mcp-client", () => ({
  callTool: vi.fn().mockResolvedValue({ valid: true }),
}));

vi.mock("@/hooks/useSources", () => ({
  useSources: () => ({ data: [] }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("ToolEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("Save button is disabled when id field is empty", () => {
    render(<ToolEditor tool={null} onSaved={vi.fn()} />, { wrapper });
    const saveBtn = screen.getByRole("button", { name: /save/i });
    expect(saveBtn).toBeDisabled();
  });

  it("Save button is disabled when id contains spaces (invalid)", async () => {
    const user = userEvent.setup();
    render(<ToolEditor tool={null} onSaved={vi.fn()} />, { wrapper });
    const idInput = screen.getAllByRole("textbox")[0];
    await user.type(idInput, "my tool");
    expect(screen.getByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("shows validation error message for id with spaces", async () => {
    const user = userEvent.setup();
    render(<ToolEditor tool={null} onSaved={vi.fn()} />, { wrapper });
    const idInput = screen.getAllByRole("textbox")[0];
    await user.type(idInput, "my tool");
    expect(screen.getByText(/must match/i)).toBeInTheDocument();
  });

  it("calls elliot_create_tool with correct args on save", async () => {
    const { callTool } = await import("@/lib/mcp-client");
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<ToolEditor tool={null} onSaved={onSaved} />, { wrapper });

    const [idInput, nameInput] = screen.getAllByRole("textbox").slice(0, 2);
    await user.type(idInput, "get_users");
    await user.type(nameInput, "Get Users");

    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      // Flat-args shape: name=snake_case id, no nested tool wrapper
      expect(callTool).toHaveBeenCalledWith(
        "elliot_create_tool",
        expect.objectContaining({ name: "get_users", description: expect.any(String) })
      );
    });
  });
});
