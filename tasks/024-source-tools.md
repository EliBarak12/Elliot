# 024 — Source MCP Tools

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 023

## Objective
MCP tools that let Claude Code / Codex discover and explore data sources.

## Files to Create

### `packages/mcp-plugin/src/tools/source-tools.ts`

Implement `registerSourceTools(server, session)`:

| Tool | Input | Action |
|------|-------|--------|
| `elliot_discover_source` | `type`, `config` (API/file/DB config), `name` | Fetch source → flatten → load SQLite → save session → return schema summary |
| `elliot_list_sources` | — | Return all sources with table names and row counts |
| `elliot_preview_source` | `tableName`, `limit?` | Return first N rows from table |
| `elliot_profile_source` | `tableName` | Return column statistics for all columns |
| `elliot_refresh_source` | `sourceId` | Re-fetch and reload into SQLite |
| `elliot_remove_source` | `sourceId` | Remove source, drop its tables, save session |

All tool inputs validated with Zod. All errors wrapped as `ElliotError` before returning to MCP.

## Done When
- [ ] `elliot_discover_source` with a CSV file returns a schema with correct column names
- [ ] `elliot_list_sources` returns all loaded sources
- [ ] `elliot_remove_source` drops the table from SQLite
