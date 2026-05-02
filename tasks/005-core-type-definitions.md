# 005 — Core Type Definitions

**Sprint**: 1 | **Estimate**: 3h | **Depends on**: 004

## Objective
Define all shared TypeScript interfaces used across the entire system. This is the single source of truth for all data shapes.

## Files to Create
- `packages/core/src/sources/types.ts` — `SourceConfig`, `ApiEndpointConfig`, `AuthConfig`, `PaginationConfig`, `FileSourceConfig`, `DbSourceConfig`, `FetchResult`, `FetchWarning`
- `packages/core/src/tools/types.ts` — `ToolDefinition`, `ParameterDefinition`, `ParameterType`, `ToolCategory`, `ResponseShape`, `SkillDefinition`, `SkillStep`, `ToolResult`
- `packages/core/src/connector/types.ts` — `ConnectorConfig`, `ProductContext`
- `packages/core/src/sqlite/types.ts` — `FlattenedTable`, `FlattenResult`, `FlattenWarning`, `ColumnMeta`, `SqliteColumnType`
- `packages/core/src/audit/types.ts` — `AuditLogEntry`
- `packages/core/src/evaluation/types.ts` — `EvalSuite`, `EvalCase`, `EvalRunResult`

See ARCHITECTURE.md Section 3 for all interface definitions.

## Done When
- [ ] All types compile with zero errors
- [ ] No `any` types in any definition
- [ ] All types exported from their respective files
