import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ParameterForm } from "@/components/playground/ParameterForm";
import type { ParameterDefinition } from "@/types/api";

function intParam(overrides: Partial<ParameterDefinition> = {}): ParameterDefinition {
  return { name: "count", type: "integer", required: true, description: "Count", default: null, ...overrides };
}

function boolParam(overrides: Partial<ParameterDefinition> = {}): ParameterDefinition {
  return { name: "active", type: "boolean", required: false, description: "Active", default: null, ...overrides };
}

describe("ParameterForm", () => {
  it("renders number input for integer param", () => {
    render(<ParameterForm parameters={[intParam()]} values={{}} onChange={vi.fn()} />);
    expect(screen.getByRole("spinbutton")).toBeInTheDocument();
  });

  it("renders checkbox for boolean param", () => {
    render(<ParameterForm parameters={[boolParam()]} values={{}} onChange={vi.fn()} />);
    expect(screen.getByRole("checkbox")).toBeInTheDocument();
  });

  it("marks required param with asterisk", () => {
    render(<ParameterForm parameters={[intParam({ required: true })]} values={{}} onChange={vi.fn()} />);
    expect(screen.getByText("*")).toBeInTheDocument();
  });

  it("calls onChange when text input changes", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const param: ParameterDefinition = { name: "query", type: "string", required: true, description: "", default: null };
    render(<ParameterForm parameters={[param]} values={{}} onChange={onChange} />);
    await user.type(screen.getByRole("textbox"), "hello");
    expect(onChange).toHaveBeenCalled();
  });
});
