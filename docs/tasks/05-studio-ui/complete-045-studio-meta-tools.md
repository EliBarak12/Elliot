# 045 — Studio Meta-Tools (Plugin Side)

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 031

## Objective
Add MCP tools to the plugin that are exclusively for Studio. Filtered out from agent tool lists.

## Files to Create

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/studio_tools.py`

Implement `register_studio_tools(mcp, session)`. Each handler checks that the caller is Studio (via a request-context header `x-client-name: elliot-studio`) and returns `ElliotError('UNAUTHORIZED')` if not.

| Tool | Input | Returns |
|------|-------|--------|
| `studio_get_connector_info` | — | Current `ConnectorConfig` + session summary |
| `studio_get_audit_log` | `limit?: int` (default 50) | Last N lines from `.elliot/audit.ndjson` |
| `studio_get_metrics` | `days?: int` (default 30) | Aggregated metrics: per-tool call count, error rate, avg latency |
| `studio_run_sql` | `sql: str` | Run raw SELECT against in-memory SQLite — for Studio debug use |

## Done When
- [ ] `studio_get_connector_info` returns session summary
- [ ] `studio_get_audit_log` returns entries from audit file
- [ ] Calling any studio tool from a non-studio client returns `UNAUTHORIZED` error
- [ ] Studio tools do NOT appear in Claude Code's `tools/list` response
