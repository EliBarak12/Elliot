import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// One self-contained HTML: MCP Apps views are served as a single ui://
// resource document, and the default host CSP blocks external requests, so
// every byte (JS, CSS) must be inlined. Determinism matters — the built file
// is committed as elliot_core package data and CI rebuilds + byte-compares.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    sourcemap: false,
    cssCodeSplit: false,
    // Stable output: no content hashes in names (everything inlines anyway),
    // no module preload polyfill noise.
    modulePreload: { polyfill: false },
    reportCompressedSize: false,
  },
  esbuild: {
    // Drop license banners that could vary across environments.
    legalComments: "none",
  },
})
