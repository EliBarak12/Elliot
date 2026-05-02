# 040 — MCP Client + React Query Hooks

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 039

## Objective
The single network layer for Studio. All plugin communication goes through here — no REST calls.

## Files to Create

### `src/lib/mcp-client.ts`
See DEVELOPMENT_GUIDE.md §6.6 for complete implementation.

Key points:
- `StreamableHTTPClientTransport(new URL('http://localhost:3000/mcp'), { sessionId: storedId, requestInit: { headers: { 'x-client-name': 'elliot-studio' } } })`
- Persist `sessionId` to `sessionStorage` on connect (fixes SDK bug #852)
- Singleton `mcpClient` — reuse across renders
- Exports: `getMcpClient()`, `callTool(name, args)`, `listTools()`

### `src/hooks/useTools.ts`
```typescript
export function useTools() {
  return useQuery({ queryKey: ['tools'], queryFn: listTools });
}
export function useCallTool() {
  return useMutation({ mutationFn: ({ name, args }) => callTool(name, args) });
}
```

### `src/hooks/useSources.ts`
```typescript
export function useSources() {
  return useQuery({ queryKey: ['sources'], queryFn: () => callTool('elliot_list_sources', {}) });
}
```

### `src/hooks/useSessionState.ts`
```typescript
export function useSessionState() {
  return useQuery({ queryKey: ['session'], queryFn: () => callTool('elliot_get_session_state', {}), refetchInterval: 5000 });
}
```

## Done When
- [ ] `useTools()` returns tool list when plugin is running
- [ ] `callTool('elliot_list_sources', {})` returns response without error
- [ ] No `/api` fetch calls anywhere in Studio
