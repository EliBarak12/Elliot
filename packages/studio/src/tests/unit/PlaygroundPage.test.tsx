import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const callToolFn = vi.fn();
vi.mock("@/hooks/useTools", () => ({
  useTools: () => ({
    data: [
      {
        id: "find_customers_by_plan",
        name: "find_customers_by_plan",
        description: "filter",
        category: "READ",
        parameters: [
          { name: "plan", type: "string", required: true, description: "" },
        ],
      },
    ],
  }),
  useCallTool: () => ({
    mutateAsync: (input: unknown) => callToolFn(input),
    isPending: false,
  }),
}));

// Replace the Radix Select with a plain <select> so jsdom can drive it.
vi.mock("@/components/ui/select", () => {
  return {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    Select: ({ value, onValueChange, children }: any) => (
      <select
        aria-label="tool-select"
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
      >
        <option value="">--</option>
        {children}
      </select>
    ),
    // The native <select> may contain only <option> elements (plus the text
    // inside them). Render the trigger/value as nothing and each item as a
    // text-only <option> keyed by value — the tests drive selection by value,
    // so the visible label is irrelevant and this keeps the mocked DOM valid.
    SelectTrigger: () => null,
    SelectValue: () => null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    SelectContent: ({ children }: any) => <>{children}</>,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    SelectItem: ({ value }: any) => <option value={value}>{value}</option>,
  };
});

import PlaygroundPage from "@/pages/PlaygroundPage";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PlaygroundPage />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  callToolFn.mockReset();
  callToolFn.mockResolvedValue({ rows: [{ id: 1 }], row_count: 1 });
});

describe("PlaygroundPage (Bug #8 regression)", () => {
  it("invokes elliot_preview_tool with tool_id+params, not the tool name directly", async () => {
    const user = userEvent.setup();
    renderPage();

    const select = screen.getByRole("combobox", { name: /tool-select/i });
    fireEvent.change(select, { target: { value: "find_customers_by_plan" } });

    // ParameterForm doesn't wire label[for], so locate the input by placeholder
    // which defaults to the parameter type ('string') when no description.
    const planInput = await screen.findByPlaceholderText("string");
    fireEvent.change(planInput, { target: { value: "enterprise" } });

    await user.click(screen.getByRole("button", { name: /run tool/i }));

    await waitFor(() => expect(callToolFn).toHaveBeenCalledTimes(1));
    const call = callToolFn.mock.calls[0][0];
    expect(call.name).toBe("elliot_preview_tool");
    expect(call.args).toMatchObject({
      tool_id: "find_customers_by_plan",
      params: { plan: "enterprise" },
    });
  });
});
