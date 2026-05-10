import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ResultViewer } from "@/components/playground/ResultViewer";

describe("ResultViewer", () => {
  it("renders JSON result", () => {
    render(<ResultViewer result={{ id: 1, name: "Alice" }} latencyMs={42} />);
    const pre = document.querySelector("pre");
    expect(pre?.textContent).toContain('"name"');
    expect(pre?.textContent).toContain('"Alice"');
  });

  it("shows latency badge", () => {
    render(<ResultViewer result={{}} latencyMs={123} />);
    expect(screen.getByText("123ms")).toBeInTheDocument();
  });

  it("shows row count badge for array result", () => {
    render(<ResultViewer result={[1, 2, 3]} latencyMs={10} />);
    expect(screen.getByText("3 rows")).toBeInTheDocument();
  });

  it("copies JSON to clipboard when copy button clicked", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(navigator, "clipboard", "get").mockReturnValue({ writeText } as unknown as Clipboard);
    render(<ResultViewer result={{ x: 1 }} latencyMs={5} />);
    await user.click(screen.getByRole("button", { name: /copy/i }));
    expect(writeText).toHaveBeenCalledWith(JSON.stringify({ x: 1 }, null, 2));
  });
});
