import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { RUNTIME_URL } from "./http";

/** MCP client for the *connector runtime* (:3001) — the server agents talk
 * to. The builder client in `mcp-client.ts` talks to the plugin (:3000),
 * whose session is empty on a fresh install; the runtime is where the
 * preloaded demo connector's tools actually live, so the welcome tour runs
 * its calls here. Deliberately minimal: no persisted session, one cached
 * connection, reconnect on next call after a failure. */

// Tools every runtime serves regardless of connector — not part of the tour.
const BUILTIN_TOOLS = new Set(["submit_feedback", "elliot_get_task"]);

export interface RuntimeTool {
  id: string;
  description: string;
}

let _client: Client | null = null;
let _initPromise: Promise<Client> | null = null;

async function getRuntimeClient(): Promise<Client> {
  if (_client) return _client;
  if (!_initPromise) {
    const transport = new StreamableHTTPClientTransport(
      new URL(`${RUNTIME_URL}/mcp/`, window.location.origin),
      { requestInit: { headers: { "x-client-name": "elliot-studio" } } },
    );
    const client = new Client({ name: "elliot-studio-welcome", version: "0.1.0" });
    _initPromise = client
      .connect(transport)
      .then(() => {
        _client = client;
        return client;
      })
      .catch((err: unknown) => {
        console.warn("[runtime-mcp] connect failed", err);
        _initPromise = null;
        throw err;
      });
  }
  return _initPromise;
}

export async function listRuntimeTools(): Promise<RuntimeTool[]> {
  const client = await getRuntimeClient();
  const result = await client.listTools();
  return result.tools
    .filter((t) => !BUILTIN_TOOLS.has(t.name))
    .map((t) => ({ id: t.name, description: t.description ?? "" }));
}

export async function callRuntimeTool(
  name: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  const client = await getRuntimeClient();
  const result = await client.callTool({ name, arguments: args });
  const content = result.content as Array<{ type: string; text?: string }>;
  const text = content?.[0]?.text ?? "{}";
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = text;
  }
  if (result.isError) {
    const err = parsed as Record<string, unknown> | undefined;
    const nested = err?.error as Record<string, unknown> | string | undefined;
    const msg =
      typeof nested === "string"
        ? nested
        : typeof nested?.message === "string"
          ? (nested.message as string)
          : text;
    throw new Error(msg);
  }
  return parsed;
}
