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

  it("pending presets are not selectable, shipped ones are", () => {
    const onChange = vi.fn();
    render(
      <ToolUITab
        toolId="list_orders"
        value={{ ...DEFAULT_UI_CONFIG }}
        onChange={onChange}
        returnFields={[]}
      />
    );
    expect(screen.getByText("Form").closest("button")).toBeDisabled();
    expect(screen.getByText("Chart").closest("button")).not.toBeDisabled();
    fireEvent.click(screen.getByText("Chart"));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ preset: "chart" }));
  });

  it("chart preset exposes x and y mapping slots", () => {
    render(
      <ToolUITab
        toolId="list_orders"
        value={{ ...DEFAULT_UI_CONFIG, preset: "chart" }}
        onChange={vi.fn()}
        returnFields={[]}
      />
    );
    expect(screen.getByText("X field")).toBeTruthy();
    expect(screen.getByText("Y fields")).toBeTruthy();
  });

  it("custom preset exposes the HTML editor", () => {
    const onChange = vi.fn();
    render(
      <ToolUITab
        toolId="list_orders"
        value={{ ...DEFAULT_UI_CONFIG, preset: "custom" }}
        onChange={onChange}
        returnFields={[]}
      />
    );
    const editor = screen.getByPlaceholderText("<!doctype html> …");
    fireEvent.change(editor, { target: { value: "<html>mine</html>" } });
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ custom_html: "<html>mine</html>" })
    );
  });
});
