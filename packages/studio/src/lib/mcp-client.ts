import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { toast } from "sonner";
import { PLUGIN_URL, authHeadersForMcp } from "./http";

const SESSION_KEY = "elliot_mcp_session_id";

let _client: Client | null = null;
let _connected = false;
let _connectionErrorShown = false;
let _initPromise: Promise<Client> | null = null;

async function _doConnect(): Promise<Client> {
  const storedId = sessionStorage.getItem(SESSION_KEY) ?? undefined;

  const transport = new StreamableHTTPClientTransport(
    new URL(`${PLUGIN_URL}/mcp/`),
    {
      sessionId: storedId,
      requestInit: {
        headers: { "x-client-name": "elliot-studio", ...authHeadersForMcp() },
      },
    }
  );

  const client = new Client({ name: "elliot-studio", version: "0.1.0" });
  try {
    await client.connect(transport);
    _client = client;
    _connected = true;
    _connectionErrorShown = false;

    const sessionId = transport.sessionId;
    if (sessionId) {
      sessionStorage.setItem(SESSION_KEY, sessionId);
    }
    return client;
  } catch (err) {
    _client = null;
    _connected = false;
    if (!_connectionErrorShown) {
      _connectionErrorShown = true;
      toast.error("Cannot connect to Elliot plugin. Is it running on :3000?", {
        duration: Infinity,
        action: {
          label: "Retry",
          onClick: () => {
            _connectionErrorShown = false;
            _initPromise = null;
            void getMcpClient();
          },
        },
      });
    }
    throw err;
  }
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
