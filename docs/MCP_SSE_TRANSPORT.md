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

## Summary of Changes vs. Previous Docs

| What | Before | Now |
|---|---|---|
| Plugin transport | `StdioServerTransport` | `StreamableHTTPServerTransport` |
| Plugin entry | `#!/usr/bin/env node` spawned by client | `http.createServer` on `:3000` |
| Claude Code config | `{ command, args }` | `{ url: "http://localhost:3000/mcp" }` |
| Session state | Lost on every reconnect | Persistent in memory |
| Runtime transport | `StreamableHTTPServerTransport` | Same (unchanged) |
| Studio transport | `StreamableHTTPClientTransport` | Same (unchanged) |
