# Studio ↔ Connector Runtime: MCP over SSE

The Studio is a pure **MCP client**. It communicates with the connector runtime exclusively over `StreamableHTTPClientTransport` (MCP over HTTP+SSE). There is no separate REST API.

---

## Why SSE-only

- Single protocol for everything — agents and the Studio speak the same language
- The connector runtime exposes one endpoint (`POST /mcp`) — no REST surface to maintain
- The Studio becomes a first-class MCP client, proving the connector works exactly as an agent would experience it
- Streaming responses (playground, long-running tool calls) work natively via SSE

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
