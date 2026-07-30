import type { Config } from "tailwindcss";

// Tokens resolve through CSS variables that DEFER to the host's MCP Apps
// style variables (--color-*, --font-*, --border-radius-*) with Elliot
// fallbacks, so a view inherits Claude's / ChatGPT's theme automatically and
// still looks right in a bare iframe. See src/styles.css for the mapping.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        muted: "var(--muted)",
        "muted-foreground": "var(--muted-foreground)",
        border: "var(--border)",
        primary: "var(--primary)",
        "primary-foreground": "var(--primary-foreground)",
        destructive: "var(--destructive)",
        success: "var(--success)",
        warning: "var(--warning)",
        card: "var(--card)",
      },
      borderRadius: {
        DEFAULT: "var(--radius)",
        lg: "calc(var(--radius) + 2px)",
        sm: "calc(var(--radius) - 2px)",
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
    },
  },
  plugins: [],
} satisfies Config;
