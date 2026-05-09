import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { toast } from "sonner";

const SESSION_KEY = "elliot_mcp_session_id";

let _client: Client | null = null;
let _connected = false;
let _connectionErrorShown = false;

async function getMcpClient(): Promise<Client> {
  if (_client && _connected) return _client;

  const storedId = sessionStorage.getItem(SESSION_KEY) ?? undefined;

  const transport = new StreamableHTTPClientTransport(
    new URL("http://localhost:3000/mcp"),
    {
      sessionId: storedId,
      requestInit: { headers: { "x-client-name": "elliot-studio" } },
    }
  );

  _client = new Client({ name: "elliot-studio", version: "0.1.0" });
  try {
    await _client.connect(transport);
    _connected = true;
    _connectionErrorShown = false;

    const sessionId = transport.sessionId;
    if (sessionId) {
      sessionStorage.setItem(SESSION_KEY, sessionId);
    }
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
            void getMcpClient();
          },
        },
      });
    }
    throw err;
  }

  return _client;
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
