# 031 — Context + Connector MCP Tools

**Sprint**: 2 | **Estimate**: 3h | **Depends on**: 030

## Objective
MCP tools for setting product context and building/exporting/running the connector.

## Files to Create

### `packages/mcp-plugin/src/tools/context-tools.ts`

| Tool | Input | Action |
|------|-------|--------|
| `elliot_set_product_context` | `name`, `domain`, `description`, `audience` | Store as `session.productContext` → save |
| `elliot_get_session_state` | — | Return full summary: sources count, tools count, skills count, connector status, productContext |

### `packages/mcp-plugin/src/tools/connector-tools.ts`

| Tool | Input | Action |
|------|-------|--------|
| `elliot_build_connector` | `toolIds`, `skillIds`, `name`, `version`, `slug` | Assemble + validate `ConnectorConfig` → store in session |
| `elliot_get_connector` | — | Return current `ConnectorConfig` or null |
| `elliot_export_connector` | `path?` | Write `ConnectorConfig` to `.elliot/connector.json` (or custom path) |
| `elliot_start_runtime` | `port?` | Spawn `@elliot/connector-runtime` as child process → return URL |
| `elliot_stop_runtime` | — | Kill child process |
| `elliot_get_connection_config` | — | Return formatted JSON snippet for agent config |

## Done When
- [ ] `elliot_build_connector` → `elliot_export_connector` → file readable and valid JSON
- [ ] `elliot_get_connection_config` returns `{ type: 'http', url: 'http://localhost:3001/mcp' }`
