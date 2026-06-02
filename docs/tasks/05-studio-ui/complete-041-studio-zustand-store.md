# 041 — Zustand Store

**Sprint**: 4 | **Estimate**: 1h | **Depends on**: 040

## Objective
Client-side UI state that isn't server state (selected items, UI toggles, etc.).

## Files to Create

### `src/lib/store.ts`
State:
- `connector: ConnectorConfig | null` — last known connector state
- `sources: SourceConfig[]`
- `tools: ToolDefinition[]`
- `selectedToolId: string | null`

Actions: `setConnector()`, `selectTool()`

Persisted fields (via `zustand/middleware persist`): `connector` only.

> **Rule**: All `@elliot/core` imports in this file must be `import type { ... }`. Never import runtime values — `better-sqlite3` and Node.js APIs will break the browser build.

## Done When
- [ ] `pnpm --filter @elliot/studio run build` exits 0 (no Node.js module errors)
- [ ] `selectedToolId` state updates trigger re-renders correctly
- [ ] `connector` persisted to localStorage across page reloads
