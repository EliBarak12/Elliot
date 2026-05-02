# 035 — Runtime MCP Server

**Sprint**: 3 | **Estimate**: 3h | **Depends on**: 034

## Objective
Standalone MCP server that exposes a deployed connector's tools to any AI agent.

## Files to Create

### `packages/connector-runtime/src/server.ts`
**`startConnectorServer(config: ConnectorConfig, opts: { port: number }): Promise<void>`**
- Express + `StreamableHTTPServerTransport` (same session-map pattern as plugin, see task 026)
- `McpServer` with two handlers:
  - `tools/list` — return all `config.tools` + `config.skills` converted to MCP schema via `toMcpToolSchema()`
  - `tools/call` — route to `executeToolCall()` or `executeSkillCall()`
- Rate limiting: in-memory token bucket, max `config.rateLimit` calls/minute per `sessionId` (default 60)
- On rate limit exceeded — return `ElliotError('RATE_LIMIT_EXCEEDED')` as tool error content

### `packages/connector-runtime/src/index.ts`
CLI entry point. See DEVELOPMENT_GUIDE.md §5.2 for exact content.
- `parseArgs` for `--port` (default 3001) and `--connector` (default `.elliot/connector.json`)
- Call `loadConnector()` then `startConnectorServer()`
- Print connection config snippet on startup

## Done When
- [ ] `node dist/index.js --connector fixture.json` starts without error
- [ ] MCP `tools/list` returns all tools from the connector
- [ ] Rate limit rejects requests after burst threshold
