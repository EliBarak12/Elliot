# 045 — Studio Meta-Tools (Plugin Side)

**Sprint**: 4 | **Estimate**: 2h | **Depends on**: 031

## Objective
Add MCP tools to the plugin that are exclusively for Studio. Filtered out from agent tool lists.

## Files to Create

### `packages/mcp-plugin/src/tools/studio-tools.ts`

Implement `registerStudioTools(server, session)`. Each handler checks `clientInfo.name === 'elliot-studio'` and throws `ElliotError('UNAUTHORIZED')` if not.

| Tool | Input | Returns |
|------|-------|--------|
| `studio_get_connector_info` | — | Current `ConnectorConfig` + session summary (source count, tool count, skill count, runtime status) |
| `studio_get_audit_log` | `limit?: number` (default 50) | Last N lines from `.elliot/audit.ndjson` parsed as `AuditLogEntry[]` |
| `studio_get_metrics` | `days?: number` (default 30) | Aggregated metrics from audit log: per-tool call count, error rate, avg latency, daily totals |
| `studio_run_sql` | `sql: string` | Run raw SELECT against in-memory SQLite engine — for Studio debug use |

## Done When
- [ ] `studio_get_connector_info` returns session summary
- [ ] `studio_get_audit_log` returns entries from audit file
- [ ] Calling any studio tool from a non-studio client returns `UNAUTHORIZED` error
- [ ] Studio tools do NOT appear in Claude Code's `tools/list` response
