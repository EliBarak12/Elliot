# 023 — MCP Server Factory

**Sprint**: 2 | **Estimate**: 2h | **Depends on**: 022

## Objective
Factory function that creates a configured `McpServer` instance with all tool groups registered.

## Files to Create

### `packages/mcp-plugin/src/server.ts`

```typescript
export function createElliotServer(session: ElliotSession): McpServer {
  const server = new McpServer({ name: 'elliot', version: '0.1.0' });
  registerSourceTools(server, session);
  registerSqlTools(server, session);
  registerToolTools(server, session);
  registerSkillTools(server, session);
  registerContextTools(server, session);
  registerConnectorTools(server, session);
  registerStudioTools(server, session);
  return server;
}
```

**Studio tool filtering** — in `registerStudioTools`, wrap each tool handler:
```typescript
if (request.clientInfo?.name !== 'elliot-studio') {
  throw new ElliotError('UNAUTHORIZED', 'This tool is only available to Elliot Studio');
}
```

## Done When
- [ ] `createElliotServer(session).listTools()` returns tools from all groups
- [ ] Studio meta-tools not visible when called without `clientInfo.name === 'elliot-studio'`
