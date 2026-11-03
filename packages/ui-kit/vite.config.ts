import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// zod 4 re-exports every message translation as `z.locales`, and the MCP
// SDK's namespace import keeps all of them in the bundle — about 250 KiB of
// languages a view never shows (zod's messages are English unless a locale
// is configured, and none is). Resolve zod's locale index to English only.
// Behaviour is unchanged; the view is ~40% smaller.
function zodEnglishOnly(): Plugin {
  const VIRTUAL = "\0zod-locales-en";
  let enPath = "";
  return {
    name: "zod-english-only",
    enforce: "pre",
    async resolveId(source, importer) {
      // classic, mini and core each re-export the locale index.
      if (!importer || !/[\\/]zod[\\/]v4[\\/](classic|mini|core)[\\/]/.test(importer)) return null;
      if (!/(^|\/)locales\/index\.js$/.test(source)) return null;
      const resolved = await this.resolve(source.replace("index.js", "en.js"), importer, {
        skipSelf: true,
      });
      if (!resolved) return null;
      enPath = resolved.id;
      return VIRTUAL;
    },
    load(id) {
      if (id !== VIRTUAL) return null;
      return `export { default as en } from ${JSON.stringify(enPath)};`;
    },
  };
}

// One self-contained HTML: MCP Apps views are served as a single ui://
// resource document, and the default host CSP blocks external requests, so
// every byte (JS, CSS) must be inlined. Determinism matters — the built file
// is committed as elliot_core package data and CI rebuilds + byte-compares.
export default defineConfig({
  plugins: [zodEnglishOnly(), react(), viteSingleFile()],
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
