import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { toast } from "sonner";
import { PLUGIN_URL } from "./http";

const SESSION_KEY = "elliot_mcp_session_id";
const RETRY_BACKOFF_MS = [500, 1500, 4000] as const;

let _client: Client | null = null;
let _connected = false;
let _connectionErrorShown = false;
let _initPromise: Promise<Client> | null = null;
let _retryTimer: ReturnType<typeof setTimeout> | null = null;

function _connectAttempt(sessionId: string | undefined): Promise<Client> {
  // PLUGIN_URL is the same-origin path `/api/plugin`; resolve it against the
  // current origin so the MCP SDK gets an absolute URL. The Studio proxy
  // forwards `/api/plugin/mcp/` to the plugin and injects the API key.
  const transport = new StreamableHTTPClientTransport(
    new URL(`${PLUGIN_URL}/mcp/`, window.location.origin),
    {
      sessionId,
      requestInit: {
        headers: { "x-client-name": "elliot-studio" },
      },
    }
  );
  const client = new Client({ name: "elliot-studio", version: "0.1.0" });
  return client.connect(transport).then(() => {
    if (transport.sessionId) {
      sessionStorage.setItem(SESSION_KEY, transport.sessionId);
    }
    return client;
  });
}

async function _doConnect(): Promise<Client> {
  const storedId = sessionStorage.getItem(SESSION_KEY) ?? undefined;
  try {
    const client = await _connectAttempt(storedId);
    _client = client;
    _connected = true;
    _connectionErrorShown = false;
    return client;
  } catch (firstErr) {
    // Common cause after a plugin restart: the stored session ID is no
    // longer recognised by the server. Try once more with a fresh session
    // before surfacing the error to the user.
    if (storedId) {
      console.warn("[mcp-client] stored session rejected, retrying with fresh session", firstErr);
      sessionStorage.removeItem(SESSION_KEY);
      try {
        const client = await _connectAttempt(undefined);
        _client = client;
        _connected = true;
        _connectionErrorShown = false;
        return client;
      } catch (secondErr) {
        _surfaceConnectError(secondErr);
        throw secondErr;
      }
    }
    _surfaceConnectError(firstErr);
    throw firstErr;
  } finally {
    if (!_connected) _initPromise = null;
  }
}

function _surfaceConnectError(err: unknown): void {
  _client = null;
  _connected = false;
  console.error("[mcp-client] connect failed", err);

  // Auto-retry quietly with exponential backoff before bothering the user.
  // If any of those attempts succeed, no toast is shown.
  _scheduleSilentRetry(0);

  if (_connectionErrorShown) return;
  _connectionErrorShown = true;
  toast.error("Cannot connect to the Elliot plugin.", {
    duration: 30_000,
    description: "Is the plugin running behind the Studio proxy? Retrying automatically.",
    action: {
      label: "Retry now",
      onClick: () => {
        _connectionErrorShown = false;
        _initPromise = null;
        void getMcpClient();
      },
    },
  });
}

function _scheduleSilentRetry(attempt: number): void {
  if (attempt >= RETRY_BACKOFF_MS.length) return;
  if (_retryTimer) clearTimeout(_retryTimer);
  _retryTimer = setTimeout(() => {
    _retryTimer = null;
    if (_connected) return;
    console.info("[mcp-client] silent retry attempt", attempt + 1);
    _initPromise = null;
    getMcpClient()
      .then(() => {
        toast.dismiss();
        toast.success("Reconnected to Elliot plugin.");
      })
      .catch(() => _scheduleSilentRetry(attempt + 1));
  }, RETRY_BACKOFF_MS[attempt]);
}

async function getMcpClient(): Promise<Client> {
  if (_client && _connected) return _client;
  if (_initPromise) return _initPromise;
  _initPromise = _doConnect().finally(() => {
    if (!_connected) _initPromise = null;
  });
  return _initPromise;
}

async function callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
  const client = await getMcpClient();
  const result = await client.callTool({ name, arguments: args });
  const content = result.content as Array<{ type: string; text?: string }>;
  const text = content[0]?.text ?? "{}";
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    parsed = text;
  }
  if (result.isError) {
    const err = parsed as Record<string, unknown> | undefined;
    const msg =
      typeof err?.error === "string"
        ? err.error
        : typeof (err?.error as Record<string, unknown> | undefined)?.message === "string"
          ? ((err!.error as Record<string, unknown>).message as string)
          : text;
    throw new Error(msg);
  }
  return parsed;
}

async function listTools(): Promise<unknown> {
  const client = await getMcpClient();
  const result = await client.callTool({ name: "elliot_list_tools", arguments: {} });
  const content = result.content as Array<{ type: string; text: string }>;
  const parsed = JSON.parse(content[0]?.text ?? "{}") as { tools?: unknown[] };
  return parsed.tools ?? [];
}

export { getMcpClient, callTool, listTools };
