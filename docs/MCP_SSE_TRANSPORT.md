# All MCP Servers Use SSE — No stdio

Both `@elliot/mcp-plugin` and `@elliot/connector-runtime` use `StreamableHTTPServerTransport` (MCP over HTTP+SSE). Neither uses `StdioServerTransport`.

This supersedes any stdio references in DEVELOPMENT_GUIDE.md or ARCHITECTURE.md.

---

## Why Not stdio

- stdio requires the MCP client to spawn the server as a subprocess each session — the server starts fresh and loses in-memory state (loaded SQLite tables, tool registry)
- SSE servers are persistent — Claude Code reconnects to the same running process, and all built-up session state (sources loaded, tools defined) is preserved across reconnections
- The Studio and other clients (Claude Desktop, Cursor) can all connect to the same running server over HTTP
- Easier to debug — the server runs in its own terminal with visible logs

---

## Architecture: Two Persistent Local Servers

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Developer's Machine                              │
│                                                                     │
│  ┌──────────────────────────────────────┐                          │
│  │  Terminal 1                          │                          │
│  │  $ elliot build                      │                          │
│  │  Elliot Plugin running on :3000      │                          │
│  │                                      │                          │
│  │  @elliot/mcp-plugin                  │                          │
│  │  (StreamableHTTPServerTransport)     │                          │
│  │  http://localhost:3000/mcp           │◄── Claude Code           │
│  └──────────────────────────────────────┘    (URL-based MCP)       │
│                                                                     │
│  ┌──────────────────────────────────────┐                          │
│  │  Terminal 2                          │                          │
│  │  $ elliot serve                      │                          │
│  │  Connector runtime on :3001          │                          │
│  │                                      │                          │
│  │  @elliot/connector-runtime           │                          │
│  │  (StreamableHTTPServerTransport)     │◄── Claude Desktop        │
│  │  http://localhost:3001/mcp           │◄── Elliot Studio         │
│  └──────────────────────────────────────┘◄── Any MCP Client        │
└─────────────────────────────────────────────────────────────────────┘
```

---

## @elliot/mcp-plugin — SSE Server

**`packages/mcp-plugin/src/index.ts`** (replaces the stdio version):

```typescript
#!/usr/bin/env node
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createServer, IncomingMessage, ServerResponse } from 'http';
import { randomUUID } from 'crypto';
import { ElliotSession } from './session.js';
import { registerAllTools } from './server.js';
import { parseArgs } from 'util';

const { values } = parseArgs({
  options: { port: { type: 'string', default: '3000' } },
});
const PORT = parseInt(values.port!, 10);

// Persistent session — survives reconnections
const session = new ElliotSession();
await session.load();

const server = new McpServer({ name: 'elliot-plugin', version: '0.1.0' });
registerAllTools(server, session);

// Active transports keyed by session ID
const transports = new Map<string, StreamableHTTPServerTransport>();

async function readBody(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', chunk => (data += chunk));
    req.on('end', () => {
      try { resolve(data ? JSON.parse(data) : {}); }
      catch (e) { reject(e); }
    });
    req.on('error', reject);
  });
}

const httpServer = createServer(async (req: IncomingMessage, res: ServerResponse) => {
  res.setHeader('Access-Control-Allow-Origin', 'http://localhost:5173');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, mcp-session-id');

  if (req.method === 'OPTIONS') {
    res.writeHead(204).end();
    return;
  }

  const url = new URL(req.url ?? '/', `http://localhost:${PORT}`);

  if (url.pathname === '/mcp') {
    if (req.method === 'POST') {
      const sessionId = req.headers['mcp-session-id'] as string | undefined;
      let transport = sessionId ? transports.get(sessionId) : undefined;

      if (!transport) {
        // New session
        transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (id) => transports.set(id, transport!),
        });
        transport.onclose = () => transports.delete(transport!.sessionId!);
        await server.connect(transport);
      }

      await transport.handleRequest(req, res, await readBody(req));

    } else if (req.method === 'GET') {
      // SSE stream for existing session
      const sessionId = url.searchParams.get('sessionId');
      const transport = transports.get(sessionId ?? '');
      if (transport) {
        await transport.handleRequest(req, res);
      } else {
        res.writeHead(404, { 'Content-Type': 'application/json' })
           .end(JSON.stringify({ error: 'Session not found' }));
      }

    } else if (req.method === 'DELETE') {
      const sessionId = url.searchParams.get('sessionId');
      transports.get(sessionId ?? '')?.close();
      transports.delete(sessionId ?? '');
      res.writeHead(200).end();

    } else {
      res.writeHead(405).end();
    }
  } else {
    res.writeHead(404).end();
  }
});

httpServer.listen(PORT, () => {
  console.log(`\n✓ Elliot Plugin running`);
  console.log(`  MCP endpoint: http://localhost:${PORT}/mcp`);
  console.log(`\n  Add to Claude Code config (~/.claude/claude_desktop_config.json):`);
  console.log(`  {`);
  console.log(`    "mcpServers": {`);
  console.log(`      "elliot": { "url": "http://localhost:${PORT}/mcp" }`);
  console.log(`    }`);
  console.log(`  }`);
});

process.on('SIGINT', async () => {
  await session.save();
  console.log('\nSession saved. Goodbye.');
  process.exit(0);
});
```

---

## Claude Code Config (URL-based, not subprocess)

Because both servers are SSE-based, Claude Code connects using `"url"` — not `"command"` + `"args"`:

**`~/.claude/claude_desktop_config.json`**:
```json
{
  "mcpServers": {
    "elliot": {
      "url": "http://localhost:3000/mcp"
    }
  }
}
```

The install script (`scripts/install-claude.mjs`) now writes:
```javascript
config.mcpServers.elliot = {
  url: `http://localhost:${PORT}/mcp`,
};
```

No `command`, no `args`, no subprocess. Claude Code connects to the running server.

---

## Starting the Servers

```bash
# Terminal 1 — Plugin (for building connectors via Claude Code)
pnpm --filter @elliot/mcp-plugin run start
# → http://localhost:3000/mcp

# Terminal 2 — Runtime (for deployed connector + Studio)
elliot serve --connector .elliot/connector.json
# → http://localhost:3001/mcp
```

Or add both to a `dev` script in the root:
```bash
# package.json (root)
"dev": "concurrently \"pnpm --filter @elliot/mcp-plugin run start\" \"pnpm --filter @elliot/studio run dev\""
```

---

## Session Persistence Advantage

Because the plugin runs as a persistent SSE server (not a short-lived stdio process), the `ElliotSession` lives in memory across the entire build session:

```
Claude Code connects via SSE to :3000
  → calls elliot_discover_source (loads 3 API tables into SQLite)
  → calls elliot_create_tool x5 (adds 5 tools to registry)
  → Claude Code is closed and reopened
  → reconnects to same running server at :3000
  → calls elliot_list_tools → all 5 tools still there ✓
  → SQLite tables still loaded ✓
```

With stdio, every reconnection spawned a fresh process and all in-memory state was gone.

---

## CORS

The plugin server allows requests from the Studio origin (`http://localhost:5173`) so the Studio can use the plugin's `studio_*` meta-tools directly if needed (e.g., to show build-time state before the connector is deployed).

---

## Summary of Changes vs. Previous Docs

| What | Before | Now |
|---|---|---|
| Plugin transport | `StdioServerTransport` | `StreamableHTTPServerTransport` |
| Plugin entry | `#!/usr/bin/env node` spawned by client | `http.createServer` on `:3000` |
| Claude Code config | `{ command, args }` | `{ url: "http://localhost:3000/mcp" }` |
| Session state | Lost on every reconnect | Persistent in memory |
| Runtime transport | `StreamableHTTPServerTransport` | Same (unchanged) |
| Studio transport | `StreamableHTTPClientTransport` | Same (unchanged) |
