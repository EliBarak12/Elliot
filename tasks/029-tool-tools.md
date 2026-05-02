# 029 — Tool MCP Tools

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 028

## Objective
MCP tools that let the agent define, update, test, and delete business tools.

## Files to Create

### `packages/mcp-plugin/src/tools/tool-tools.ts`

Implement `registerToolTools(server, session)`:

| Tool | Input | Action |
|------|-------|--------|
| `elliot_create_tool` | Full `ToolDefinition` fields | Validate → add to registry → save session |
| `elliot_update_tool` | `toolId`, partial fields | Merge → re-validate → save session |
| `elliot_list_tools` | — | Return all tools with id, name, category, description |
| `elliot_get_tool` | `toolId` | Return full tool definition |
| `elliot_delete_tool` | `toolId` | Remove from registry → save session |
| `elliot_preview_tool` | `toolId`, `params` | Execute tool against current SQLite → return rows |
| `elliot_validate_sql` | `sql`, `parameters?` | Validate SQL + param binding → return issues list |

## Done When
- [ ] `elliot_create_tool` → `elliot_get_tool` returns same definition
- [ ] `elliot_preview_tool` returns real data from SQLite
- [ ] `elliot_delete_tool` removes from `elliot_list_tools`
