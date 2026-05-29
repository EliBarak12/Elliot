import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";
import type { ClientRequest } from "node:http";
import type { ProxyOptions } from "vite";

// Dev mirror of the production nginx reverse-proxy: the browser only ever
// talks same-origin `/api/plugin` + `/api/runtime`, and this dev server
// forwards to the real plugin/runtime, injecting X-Elliot-Key server-side so
// the key never reaches the browser. Targets + key come from the process
// env (set by `make dev` / the e2e harness), never from the client bundle.
const PLUGIN_TARGET = process.env.VITE_PLUGIN_URL ?? "http://127.0.0.1:3000";
const RUNTIME_TARGET = process.env.VITE_RUNTIME_URL ?? "http://127.0.0.1:3001";
const API_KEY = process.env.ELLIOT_API_KEY ?? "";

function injectKey(prefix: string): ProxyOptions {
  return {
    target: prefix === "plugin" ? PLUGIN_TARGET : RUNTIME_TARGET,
    changeOrigin: true,
    ws: true,
    rewrite: (p: string) => p.replace(new RegExp(`^/api/${prefix}`), ""),
    configure: (proxy) => {
      proxy.on("proxyReq", (proxyReq: ClientRequest) => {
        if (API_KEY) proxyReq.setHeader("X-Elliot-Key", API_KEY);
      });
    },
  };
}

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api/plugin": injectKey("plugin"),
      "/api/runtime": injectKey("runtime"),
    },
  },
});
