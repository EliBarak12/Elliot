import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ToolCard } from "@/components/tools/ToolCard";
import type { ToolDefinition } from "@/types/api";

const BASE_TOOL: ToolDefinition = {
  id: "get_users",
  name: "Get Users",
  description: "Returns a list of users",
  category: "READ",
  source_ids: [],
  sql: null,
  parameters: [],
};

function makeTool(overrides: Partial<ToolDefinition> = {}): ToolDefinition {
  return { ...BASE_TOOL, ...overrides };
}

describe("ToolCard", () => {
  it("renders tool name and description", () => {
    render(<ToolCard tool={makeTool()} selected={false} onClick={vi.fn()} />);
    expect(screen.getByText("Get Users")).toBeInTheDocument();
    expect(screen.getByText("Returns a list of users")).toBeInTheDocument();
  });

  it.each([
    ["READ", "bg-primary/10"],
    ["WRITE", "bg-warning/10"],
    ["ACTION", "bg-destructive/10"],
    ["AGGREGATE", "bg-secondary"],
  ] as const)("shows correct badge style for %s category", (category, expectedClass) => {
    render(<ToolCard tool={makeTool({ category })} selected={false} onClick={vi.fn()} />);
    const badge = screen.getByText(category);
    expect(badge).toHaveClass(expectedClass);
  });

  it("calls onClick when card is clicked", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();
    render(<ToolCard tool={makeTool()} selected={false} onClick={handleClick} />);
    await user.click(screen.getByRole("button"));
    expect(handleClick).toHaveBeenCalledOnce();
  });
});
