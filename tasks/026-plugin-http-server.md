# 026 — Plugin HTTP Server

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 025

## Objective
Express HTTP server with `StreamableHTTPServerTransport`. This is the entry point that Claude Code and Studio connect to.

## Files to Create

### `packages/mcp-plugin/src/index.ts`

See DEVELOPMENT_GUIDE.md §4.2 for the complete implementation. Key points:
- Port from `process.env.ELLIOT_PORT` (default `3000`)
- CORS: allow `http://localhost:5173` for Studio
- `Map<sessionId, StreamableHTTPServerTransport>` for routing multiple concurrent connections
- `app.all('/mcp', ...)`: route to existing transport by `Mcp-Session-Id` header, or create new transport + server pair
- `transport.onSessionId` → add to map; `transport.onClose` → remove from map
- **One `ElliotSession` instance** created before the server starts; passed to every `createElliotServer()` call
- Graceful shutdown on `SIGINT`: `session.save()` then `httpServer.close()`

## Done When
- [ ] `tsx src/index.ts` starts without error
- [ ] `curl http://localhost:3000/mcp` receives a valid MCP response
- [ ] Two concurrent connections (Claude Code + Studio) both work
- [ ] SIGINT saves session before exit
