# 036 — OpenAI Protocol + Audit Log

**Sprint**: 3 | **Estimate**: 2h | **Depends on**: 035

## Objective
OpenAI function-calling endpoint and append-only audit log for every tool call.

## Files to Create

### `packages/connector-runtime/src/protocols/openai.ts`
Express router mounted at `/openai`:
- `GET /openai/tools` — return all tools as OpenAI function-calling schema array (use `toOpenAiFunction()` from core)
- `POST /openai/call/:toolName` — parse body as `{ arguments: {...} }`, call `executeToolCall()`, return `{ result: rows, meta }`

### `packages/connector-runtime/src/audit.ts`
**`append(entry: AuditLogEntry, auditPath: string): void`** (sync, fire-and-forget via `fs.appendFileSync`)
- Write one JSON line per call to `.elliot/audit.ndjson`
- `AuditLogEntry` fields: `timestamp`, `toolName`, `sessionId`, `params` (redacted), `rowCount`, `latencyMs`, `error?: string`

**`readAuditLog(auditPath: string, limit: number): AuditLogEntry[]`**
- Read last `limit` lines from file (efficient tail-read)
- Parse each line as JSON

**`aggregateMetrics(entries: AuditLogEntry[]): MetricsSummary`**
- Per-tool: call count, error count, avg/p95 latency
- Overall: total calls, total errors, date range

## Done When
- [ ] `GET /openai/tools` returns valid OpenAI function schemas
- [ ] Every tool call appends a line to `audit.ndjson`
- [ ] `aggregateMetrics` returns correct counts from fixture log entries
