import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const callToolResultFn = vi.fn();
vi.mock("@/lib/mcp-client", () => ({
  callToolResult: (name: string, args: Record<string, unknown>) => callToolResultFn(name, args),
  callTool: vi.fn(),
}));

import { AppPreviewHost, AppResultView } from "@/components/playground/AppPreviewHost";

describe("AppPreviewHost", () => {
  it("renders the view in a sandboxed iframe", () => {
    render(
      <AppPreviewHost
        html="<html><body>view</body></html>"
        toolId="list_orders"
        args={{}}
        result={null}
      />
    );
    const iframe = screen.getByTitle("App view for list_orders");
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
    expect(iframe.getAttribute("srcdoc")).toContain("view");
    expect(screen.getByText("loading view…")).toBeInTheDocument();
  });
});

describe("AppResultView", () => {
  beforeEach(() => callToolResultFn.mockReset());

  it("fetches the built template via elliot_preview_tool_ui and mounts the host", async () => {
    callToolResultFn.mockResolvedValue({
      data: { html: "<html><body>built view</body></html>", uri: "ui://shop/list_orders" },
      content: [],
      structuredContent: null,
      meta: null,
      isError: false,
    });
    render(
      <AppResultView toolId="list_orders" args={{}} resultData={{ rows: [{ id: 1 }], count: 1 }} />
    );
    await waitFor(() => {
      expect(screen.getByTestId("app-preview-host")).toBeInTheDocument();
    });
    expect(callToolResultFn).toHaveBeenCalledWith("elliot_preview_tool_ui", {
      tool_id: "list_orders",
    });
  });

  it("surfaces template errors instead of a blank frame", async () => {
    callToolResultFn.mockResolvedValue({
      data: { error: "Tool not found: nope" },
      content: [],
      structuredContent: null,
      meta: null,
      isError: false,
    });
    render(<AppResultView toolId="nope" args={{}} resultData={null} />);
    await waitFor(() => {
      expect(screen.getByText(/Could not load the view/)).toBeInTheDocument();
    });
  });
});
