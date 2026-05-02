# 021 — Core Public API + Remaining Tests

**Sprint**: 1 | **Estimate**: 2h | **Depends on**: 019, 020

## Objective
Expose a clean public API from `@elliot/core` and write remaining unit tests to hit coverage thresholds.

## Files to Create / Modify

### `packages/core/src/index.ts`
Re-export everything packages outside `@elliot/core` need:
```typescript
export type { SourceConfig, ApiEndpointConfig, AuthConfig, /* ... */ } from './sources/types.js';
export type { ToolDefinition, SkillDefinition, ToolResult, /* ... */ } from './tools/types.js';
export type { ConnectorConfig, ProductContext } from './connector/types.js';
export type { FlattenResult, FlattenedTable, FlattenWarning } from './sqlite/types.js';
export { SQLiteEngine } from './sqlite/engine.js';
export { flatten } from './sqlite/flattener.js';
export { ToolRegistry } from './tools/registry.js';
export { executeTool } from './tools/executor.js';
export { executeSkill } from './tools/skill-runner.js';
export { ConnectorBuilder } from './connector/builder.js';
export { serializeConnector, deserializeConnector } from './connector/serializer.js';
export { WorkspaceStore } from './workspace/store.js';
export { ElliotError } from './errors.js';
```

### `packages/core/tests/unit/executor.test.ts`
### `packages/core/tests/unit/skill-runner.test.ts`
### `packages/core/tests/unit/connector-builder.test.ts`

## Done When
- [ ] `pnpm --filter @elliot/core test:coverage` exits 0
- [ ] Line coverage ≥ 85% across `packages/core/src/`
- [ ] All exports accessible from `import { X } from '@elliot/core'`
