import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const callToolFn = vi.fn();
vi.mock("@/lib/mcp-client", () => ({
  callTool: (name: string, args: Record<string, unknown>) => callToolFn(name, args),
}));

import { BrandingCard } from "@/components/connector/BrandingCard";

describe("BrandingCard", () => {
  beforeEach(() => {
    callToolFn.mockReset();
    callToolFn.mockImplementation((name: string) => {
      if (name === "elliot_get_branding") return Promise.resolve({ branding: null });
      return Promise.resolve({ status: "ok" });
    });
  });

  it("loads existing branding into the fields", async () => {
    callToolFn.mockImplementation((name: string) => {
      if (name === "elliot_get_branding") {
        return Promise.resolve({
          branding: { accent: "#c02434", accent_dark: null, logo: "https://cdn.x/logo.png" },
        });
      }
      return Promise.resolve({ status: "ok" });
    });
    render(<BrandingCard />);
    await waitFor(() => {
      expect((screen.getByLabelText("Accent color") as HTMLInputElement).value).toBe("#c02434");
    });
    expect((screen.getByLabelText("Logo") as HTMLInputElement).value).toBe(
      "https://cdn.x/logo.png"
    );
  });

  it("saves via elliot_set_branding with clear+fields (full replace)", async () => {
    render(<BrandingCard />);
    await waitFor(() =>
      expect(callToolFn).toHaveBeenCalledWith("elliot_get_branding", expect.anything())
    );
    fireEvent.change(screen.getByLabelText("Accent color"), { target: { value: "#123abc" } });
    fireEvent.click(screen.getByRole("button", { name: /save branding/i }));
    await waitFor(() =>
      expect(callToolFn).toHaveBeenCalledWith("elliot_set_branding", {
        clear: true,
        accent: "#123abc",
      })
    );
    await screen.findByText(/branding saved/i);
  });

  it("rejects an invalid hex before calling the tool", async () => {
    render(<BrandingCard />);
    await waitFor(() =>
      expect(callToolFn).toHaveBeenCalledWith("elliot_get_branding", expect.anything())
    );
    fireEvent.change(screen.getByLabelText("Accent color"), { target: { value: "red" } });
    expect(screen.getByText(/must be a hex color/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /save branding/i })).toBeDisabled();
  });

  it("warns when a data: logo is oversized", async () => {
    callToolFn.mockImplementation((name: string) => {
      if (name === "elliot_get_branding") {
        return Promise.resolve({
          branding: { accent: null, accent_dark: null, logo: "data:image/png;base64," + "A".repeat(70 * 1024) },
        });
      }
      return Promise.resolve({ status: "ok" });
    });
    render(<BrandingCard />);
    await screen.findByText(/inlined into every view/i);
  });
});
