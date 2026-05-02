# 025 — SQL MCP Tools

**Sprint**: 2 | **Estimate**: 2h | **Depends on**: 024

## Objective
MCP tools that let the agent explore the in-memory SQLite schema and run queries.

## Files to Create

### `packages/mcp-plugin/src/tools/sql-tools.ts`

Implement `registerSqlTools(server, session)`:

| Tool | Input | Action |
|------|-------|--------|
| `elliot_get_schema` | — | Return all table names + column definitions |
| `elliot_query_sql` | `sql`, `params?` | Validate + run SELECT → return rows + meta |
| `elliot_sample_data` | `tableName`, `limit?` | Return N random rows |
| `elliot_profile_column` | `tableName`, `columnName` | Return min/max/nullCount/distinctCount/topValues |
| `elliot_explain_query` | `sql` | Run `EXPLAIN QUERY PLAN` and return output |
| `elliot_validate_sql` | `sql` | Validate SQL without executing, return valid/invalid + reason |

## Done When
- [ ] `elliot_query_sql` with a valid SELECT returns rows
- [ ] `elliot_query_sql` with `DROP TABLE` returns error (not throws)
- [ ] `elliot_get_schema` returns all loaded table names
