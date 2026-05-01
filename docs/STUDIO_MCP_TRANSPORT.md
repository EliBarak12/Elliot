# Studio ↔ Connector Runtime: MCP over SSE

The Studio is a pure **MCP client**. It communicates with the connector runtime exclusively over `StreamableHTTPClientTransport` (MCP over HTTP+SSE). There is no separate REST API.

---

## Why SSE-only

- Single protocol for everything — agents and the Studio speak the same language
- The connector runtime exposes one endpoint (`POST /mcp`) — no REST surface to maintain
- The Studio becomes a first-class MCP client, proving the connector works exactly as an agent would experience it
- Streaming responses (playground, long-running tool calls) work natively via SSE

---

## Transport Setup

### Connector Runtime — Server Side

The runtime uses `StreamableHTTPServerTransport` from `@modelcontextprotocol/sdk`:

```typescript
// packages/connector-runtime/src/server.ts
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createServer } from 'http';
import { randomUUID } from 'crypto';

export async function startConnectorServer(config: ConnectorConfig, opts: { port: number }) {
  const server = new McpServer({ name: config.slug, version: config.version });

  // Register all user-defined tools
  registerConnectorTools(server, config);

  // Register studio meta-tools (Studio-only, filtered from agent tool lists)
  registerStudioTools(server, config);

  const httpServer = createServer(async (req, res) => {
    if (req.method === 'POST' && req.url === '/mcp') {
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        onsessioninitialized: (sessionId) => {
          activeSessions.set(sessionId, transport);
        },
      });

      transport.onclose = () => activeSessions.delete(transport.sessionId!);

      await server.connect(transport);
      await transport.handleRequest(req, res, await readBody(req));
    } else if (req.method === 'GET' && req.url === '/mcp') {
      // SSE stream endpoint for ongoing sessions
      const sessionId = new URL(req.url, 'http://x').searchParams.get('sessionId');
      const transport = activeSessions.get(sessionId ?? '');
      if (transport) await transport.handleRequest(req, res);
      else res.writeHead(404).end();
    } else if (req.method === 'DELETE' && req.url === '/mcp') {
      // Session termination
      const sessionId = new URL(req.url, 'http://x').searchParams.get('sessionId');
      activeSessions.get(sessionId ?? '')?.close();
      res.writeHead(200).end();
    } else {
      res.writeHead(404).end();
    }
  });

  const activeSessions = new Map<string, StreamableHTTPServerTransport>();

  httpServer.listen(opts.port);
}
```

### Studio — Client Side

The Studio creates one `Client` instance per component tree (stored in Zustand) and keeps it alive for the session:

```typescript
// packages/studio/src/lib/mcp-client.ts
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

let _client: Client | null = null;

export async function getMcpClient(runtimeUrl = 'http://localhost:3001/mcp'): Promise<Client> {
  if (_client) return _client;

  const client = new Client({ name: 'elliot-studio', version: '0.1.0' });
  const transport = new StreamableHTTPClientTransport(new URL(runtimeUrl));

  await client.connect(transport);
  _client = client;
  return client;
}

export function disconnectMcpClient(): void {
  _client?.close();
  _client = null;
}
```

Replace the old `src/lib/api.ts` REST wrapper entirely with this client.

### React Query Integration

```typescript
// packages/studio/src/hooks/use-connector.ts
import { useQuery, useMutation } from '@tanstack/react-query';
import { getMcpClient } from '@/lib/mcp-client';

export function useTools() {
  return useQuery({
    queryKey: ['tools'],
    queryFn: async () => {
      const client = await getMcpClient();
      const { tools } = await client.listTools();
      return tools;
    },
  });
}

export function useCallTool() {
  return useMutation({
    mutationFn: async ({ name, args }: { name: string; args: Record<string, unknown> }) => {
      const client = await getMcpClient();
      return client.callTool({ name, arguments: args });
    },
  });
}
```

---

## Studio Meta-Tools (Studio-Only)

The connector runtime exposes extra "meta-tools" that the Studio uses for management and observability. These are registered on the runtime but **filtered out from `tools/list` when called by a non-Studio agent** (identified by the MCP client name in the `initialize` handshake).

| Meta-Tool | Purpose |
|---|---|
| `studio_get_connector_info` | Returns full `ConnectorConfig` (name, version, tool list, source list) |
| `studio_get_metrics` | Returns aggregated metrics from audit log (counts, latency, success rate) |
| `studio_get_audit_log` | Returns last N audit log entries |
| `studio_get_source_schema` | Returns SQLite schema for a specific source table |
| `studio_refresh_source` | Re-fetches a source and reloads its SQLite tables |
| `studio_run_sql` | Run a SELECT query on in-memory SQLite (Studio tool builder helper) |
| `studio_playground_chat` | Runs a Claude chat turn using the connector's tools; returns streaming response |

```typescript
// packages/connector-runtime/src/studio-tools.ts
export function registerStudioTools(server: McpServer, config: ConnectorConfig, context: RuntimeContext) {
  server.tool('studio_get_metrics', {}, async () => {
    const entries = await readAuditLog(100);
    return {
      content: [{
        type: 'text',
        text: JSON.stringify(aggregateMetrics(entries)),
      }],
    };
  });

  server.tool('studio_get_connector_info', {}, async () => ({
    content: [{ type: 'text', text: JSON.stringify(config) }],
  }));

  server.tool(
    'studio_get_audit_log',
    { limit: z.number().int().min(1).max(500).default(50) },
    async ({ limit }) => {
      const entries = await readAuditLog(limit);
      return { content: [{ type: 'text', text: JSON.stringify(entries) }] };
    },
  );

  server.tool(
    'studio_run_sql',
    { sql: z.string(), params: z.record(z.unknown()).optional() },
    async ({ sql, params }) => {
      validateToolSql(sql);
      const rows = context.engine.query(sql, params ?? {});
      return { content: [{ type: 'text', text: JSON.stringify(rows) }] };
    },
  );
}
```

### Filtering Meta-Tools from Agent Clients

```typescript
// In the tools/list handler
async function handleListTools(clientInfo: { name: string }) {
  const isStudio = clientInfo.name === 'elliot-studio';
  const allTools = registry.getAll();
  return {
    tools: allTools
      .filter(t => isStudio || !t.name.startsWith('studio_'))
      .map(t => toMcpToolDef(t)),
  };
}
```

---

## Playground via MCP

The Playground page calls `studio_playground_chat` via MCP. The runtime runs the Claude API call server-side, uses the connector's tools (calling them internally), and streams the conversation back as MCP content.

```typescript
// Simplified playground flow

// Studio sends:
client.callTool({
  name: 'studio_playground_chat',
  arguments: {
    messages: [{ role: 'user', content: 'How many active customers do we have?' }],
    includeToolCalls: true,
  },
});

// Runtime runs Claude with connector tools, returns:
{
  content: [{ type: 'text', text: JSON.stringify({
    response: "There are 142 active customers.",
    toolCalls: [
      { name: 'get_customer_count', arguments: { status: 'active' }, result: [{ count: 142 }], latencyMs: 234 }
    ]
  })}]
}
```

---

## Connection Status in Studio

The Studio header shows a live connection indicator:

```typescript
// packages/studio/src/hooks/use-runtime-connection.ts
export function useRuntimeConnection(url: string) {
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');

  useEffect(() => {
    setStatus('connecting');
    getMcpClient(url)
      .then(() => setStatus('connected'))
      .catch(() => setStatus('disconnected'));

    return () => {
      disconnectMcpClient();
      setStatus('disconnected');
    };
  }, [url]);

  return status;
}
```

---

## Removing the REST API from DEVELOPMENT_GUIDE

Replace `packages/studio/src/lib/api.ts` (REST fetch wrapper) with `packages/studio/src/lib/mcp-client.ts` as shown above. All Studio data fetching goes through `useQuery` hooks that call `getMcpClient()`.

The connector runtime's `server.ts` no longer needs any HTTP routes other than the three MCP endpoints (`POST`, `GET`, `DELETE` on `/mcp`). Delete the `src/protocols/rest.ts` file and the `/studio/...` route definitions.

---

## Package Dependencies Update

Add to `packages/studio/package.json`:
```json
{
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0"
  }
}
```

The Studio is now a proper MCP client — it ships `@modelcontextprotocol/sdk` just like any other agent integration.
