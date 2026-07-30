import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const callToolFn = vi.fn();
vi.mock("@/lib/mcp-client", () => ({
  callTool: (name: string, args: Record<string, unknown>) => callToolFn(name, args),
  callToolResult: vi.fn().mockResolvedValue({
    data: { html: "<html></html>" },
    content: [],
    structuredContent: null,
    meta: null,
    isError: false,
  }),
}));

import { ToolUITab, DEFAULT_UI_CONFIG } from "@/components/tools/ToolUITab";

describe("ToolUITab", () => {
  beforeEach(() => callToolFn.mockReset());

  it("starts disabled when the tool has no ui config", () => {
    render(
      <ToolUITab toolId="list_orders" value={null} onChange={vi.fn()} returnFields={[]} />
    );
    const checkbox = screen.getByRole("checkbox");
    expect((checkbox as HTMLInputElement).checked).toBe(false);
    // No preset picker until enabled.
    expect(screen.queryByText("Preset:")).toBeNull();
  });

  it("enabling produces the default ui config", () => {
    const onChange = vi.fn();
    render(
      <ToolUITab toolId="list_orders" value={null} onChange={onChange} returnFields={[]} />
    );
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ enabled: true, preset: "auto" }));
  });

  it("preset selection and mapping are reported through onChange", () => {
    const onChange = vi.fn();
    render(
      <ToolUITab
        toolId="list_orders"
        value={{ ...DEFAULT_UI_CONFIG, preset: "table" }}
        onChange={onChange}
        returnFields={[{ field: "id" }, { field: "total", alias: "amount" }]}
      />
    );
    fireEvent.click(screen.getByText("Metrics"));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ preset: "metric" }));

    const mapping = screen.getByPlaceholderText("id,amount");
    fireEvent.change(mapping, { target: { value: "id,total" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ mapping: expect.objectContaining({ columns: "id,total" }) })
    );
  });

  it("pending presets are not selectable", () => {
    const onChange = vi.fn();
    render(
      <ToolUITab
        toolId="list_orders"
        value={{ ...DEFAULT_UI_CONFIG }}
        onChange={onChange}
        returnFields={[]}
      />
    );
    const chart = screen.getByText("Chart").closest("button");
    expect(chart).toBeDisabled();
  });
});
