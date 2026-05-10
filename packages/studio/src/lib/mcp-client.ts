import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { toast } from "sonner";

const SESSION_KEY = "elliot_mcp_session_id";

let _client: Client | null = null;
let _connected = false;
let _connectionErrorShown = false;
let _initPromise: Promise<Client> | null = null;

async function _doConnect(): Promise<Client> {
  const storedId = sessionStorage.getItem(SESSION_KEY) ?? undefined;

  const transport = new StreamableHTTPClientTransport(
    new URL("http://localhost:3000/mcp/"),
    {
      sessionId: storedId,
      requestInit: { headers: { "x-client-name": "elliot-studio" } },
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
  return result;
}

async function listTools(): Promise<unknown> {
  const client = await getMcpClient();
  const result = await client.listTools();
  return result.tools;
}

export { getMcpClient, callTool, listTools };
