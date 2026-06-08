# Elliot Cloud — Launch Gateway E2E Test Findings

Test session started: 2026-06-08
Tester: Claude Code (final launch gateway)
Branch: claude/elliot-cloud-launch-test-DfhKz

## Environment constraints discovered
- No `ANTHROPIC_API_KEY` in sandbox → cannot literally spawn 100 authenticated Claude Code agents.
- Production MCP endpoint `https://api.elliot-cloud.com/b/mcp` is UNREACHABLE from sandbox (curl 000); `elliot-cloud.com` root returns 200.
- Public APIs reachable for real testing: jsonplaceholder, restcountries, pokeapi (all 200). github-api 403 (needs auth).
- Toolchain present: uv 0.8.17, node 22, pnpm 10.33, claude CLI 2.1.168. Python .venv installed; Studio node_modules NOT installed.

## Approach
Strongest feasible equivalent of "100 real users": boot the real stack locally and drive the
actual MCP connector-build tools (discover -> build -> lint -> eval -> deploy) across many diverse
real-world API scenarios as scripted agent sessions, then verify Studio surfaces what was built.
Find failures, fix, re-run until clean.

---

## FINDINGS LOG

### [BASELINE] Mandatory check suite — ALL PASS (2026-06-08)
- `ruff check .` — All checks passed
- `ruff format --check .` — 217 files formatted
- `mypy` (core, mcp-plugin, connector-runtime) — no issues, 104 files
- `pytest` — 1131 passed in 19.31s
- Studio `typecheck` (tsc --noEmit) — pass
- Studio `test` — 68 passed (15 files)
- NOTE: Studio test logs a React warning: "<p> cannot contain a nested <div>" (non-fatal, cosmetic). Candidate cleanup.

Static/test baseline is GREEN. Proceeding to live end-to-end behavioral testing.

### [ARCH-1] Local builder plugin is single-tenant per process (by design)
`packages/mcp-plugin/src/elliot_mcp_plugin/main.py:21` creates ONE module-global `ElliotSession`,
captured into every tool closure via `create_elliot_server(session)`. All MCP connections to a
plugin process share the same sources/tools/runtime state. This is correct for the *local* builder
(one product engineer, localhost) but means true 100-user isolation belongs to Elliot **Cloud**
(separate repo). Harness implication: drive many diverse scenarios sequentially against one
plugin (namespaced), not 100 isolated concurrent build sessions. Concurrency tested separately
at the read-only wire level.

### [INFRA-1] Production MCP endpoint unreachable from sandbox
`.mcp.json` -> `https://api.elliot-cloud.com/b/mcp` returns curl 000 (no connect) from here,
while `elliot-cloud.com` root is 200. Cannot exercise the hosted Cloud builder from this sandbox.
Testing the local stack (the same code the Cloud builder serves) instead.

### [OBS-1] Column-name normalization lowercases camelCase without snake-casing (low severity, cosmetic)
`elliot_core/sqlite/column_namer.safe_name` lowercases + replaces non-alnum, so a real API field
`userId` becomes column `userid` (not `user_id`). Discovered against jsonplaceholder /posts.
- NOT a functional bug: SQLite identifier matching is case-insensitive, so agent SQL written as
  `userId` still resolves to `userid` (verified — preview/build/lint all pass).
- AX-fidelity nit: the schema an agent sees (`userid`) differs from the API's documented field
  (`userId`). A future improvement would snake-case camelCase (`user_id`) for readability, but that
  changes column names broadly (existing tests/connectors depend on current names) → out of scope
  for launch gateway; logged as a recommendation, not changed.
Action: harness expectations corrected to the normalized names; SQL intentionally keeps camelCase
in some scenarios to regression-test case-insensitive resolution.

### [BUG-1 — FIXED] Deeply-nested objects crash discovery with cryptic INVALID_IDENTIFIER (HIGH)
Reproduced live against `pokeapi /pokemon/ditto` (a single-object, deeply-nested REST response —
an extremely common real-world shape: pokeapi, Stripe expanded objects, GitHub, etc.).
- Root cause: `elliot_core/sqlite/flattener.py` inlines nested objects into composite column names
  (e.g. `sprites_versions_generation_viii_brilliant_diamond_shining_pearl_front_default` = 78 chars).
  `column_namer.safe_name` sanitizes characters but never bounds LENGTH. At table creation,
  `engine.load_table` → `safe_ident` rejects any identifier outside `^[A-Za-z_][A-Za-z0-9_]{0,62}$`
  (max 63 chars), raising `[INVALID_IDENTIFIER]` and aborting the ENTIRE `elliot_discover_source`
  call. 18 columns in ditto exceeded the limit. Violates principle #3 (actionable errors) and
  breaks core functionality on real APIs.
- Fix: added `bound_name()` + `MAX_IDENTIFIER_LENGTH=63` in `column_namer.py` (deterministic
  truncate-with-hash, collision-safe, no-op for short names). Flattener now bounds row keys and
  child-table names at finalization (`_bound_row_keys`), rewriting schema + rows together so they
  stay consistent. Verified: 0 invalid identifiers on live ditto, engine loads all 137 columns,
  data still queryable. Added regression tests in test_column_namer.py + test_flattener.py.

### [OBS-2] Tool errors via to_mcp_error_content don't set MCP isError (medium — AX/observability)
`elliot_core/errors.to_mcp_error_content` returns `{"type":"text","text":"[CODE] message"}` as a
normal tool RESULT. FastMCP only sets `isError=True` when a tool RAISES, so these error returns
come back with `isError=False`. Consequences:
- An MCP client / coding agent that keys off `isError` (the standard signal) sees a *successful*
  call whose body is an error sentinel — it must string-parse `"[CODE] ..."` to notice failure.
- Two error shapes coexist in the tool layer: soft `{"error": "..."}` (used by many handlers) and
  the `{"type":"text","text":"[CODE] ..."}` sentinel — neither matches CLAUDE.md's documented
  `{"error":{"code","message","details"}}` contract.
- The repo's own e2e helper `dev/e2e/helpers/mcp_client.call_tool_json` only raises on `isError`,
  so it shares this blind spot (false greens possible).
Recommendation (not changed — broad blast radius, many tests assert the `[CODE]` text): either raise
inside FastMCP tools so `isError` is set, or standardize on the documented `{"error":{...}}` shape.
Harness hardened to also flag `[CODE]` sentinels so it doesn't report false passes.

### [BUG-2 — FIXED] build_connector silently builds an empty connector for unknown tool_ids (MEDIUM)
Found via negative harness check N8. `elliot_build_connector(tool_ids=["does_not_exist"])` filtered
unknown ids out silently and returned `{"status":"built","tool_count":0}` — an agent with a typo'd
tool id would think it succeeded and could deploy an EMPTY connector. Violates principle #3.
- Fix: `connector_tools.elliot_build_connector` now validates `tool_ids`/`skill_ids` against the
  registry and raises an actionable `VALIDATION_UNKNOWN_TOOL` / `VALIDATION_UNKNOWN_SKILL` listing
  the missing and the available ids. Added two unit tests. Verified: N8 now returns
  `[VALIDATION_UNKNOWN_TOOL] Unknown tool_id(s): does_not_exist. Available: ...`.

### [NEG] Error-path / security checks — 10/10 PASS (after BUG-2 fix)
Drove the plugin through deliberately bad input over MCP. All handled gracefully with structured,
actionable errors and the server stayed healthy throughout:
- 404 upstream → `[UPSTREAM_FETCH_FAILED] HTTP 404 ... after 3 attempts`
- invalid source_type → lists valid values
- invalid SQL → `[INVALID_SQL] near "FROM": syntax error`
- write SQL (DELETE) → `[INVALID_SQL] Forbidden keyword: DELETE` (read-only invariant holds)
- statement stacking (`SELECT 1; DROP TABLE`) → `[INVALID_SQL] Multiple statements not allowed`
- missing required param → `[VALIDATION_REQUIRED] Missing required parameter(s): id`
- server still healthy after the error storm.

### [OBS-3] Non-JSON upstream surfaces as INTERNAL_ERROR (low)
Discovering an HTML endpoint (https://example.com) returns
`[INTERNAL_ERROR] Expecting value: line 1 column 1 (char 0)` — a leaked JSON-decoder message.
Not a crash (handled, server stays up) but not actionable. Recommend mapping JSON-parse failures
on REST discovery to an `UPSTREAM_*` error like "endpoint did not return JSON (got text/html)".
Logged as a recommendation; not changed.

### [OBS-4] Plugin tests are order/state-dependent under subset selection (low)
Running a `-k` subset of `packages/mcp-plugin/tests` fails ~19 tests across unrelated files
(oauth, session, studio), because they share the module-global `ElliotSession` (see ARCH-1) and
depend on full-suite ordering. The canonical full-suite run passes (300/300). Recommend per-test
session isolation so subsets are runnable. Not changed (out of scope; mandatory command is green).

### [OBSV] Observability loop — 19/19 PASS (build → deploy → agent → Studio data)
Proved the full path Studio renders from. Built a dummyjson connector, deployed the runtime,
connected an MCP *agent* to :3001/mcp/, called the deployed tool 3× plus a junk-arg call, then:
- runtime `/v1/health` → healthy, serving the connector
- `/v1/sessions` → 1 agent session recorded
- `/v1/audit` → 4 tool-call entries
- `/v1/metrics/token-efficiency` → per-tool call_count=4, avg_tokens=165, duration + error tracking
- plugin `elliot_session_summary` / `studio_get_connector_info` / `studio_get_metrics` /
  `studio_get_audit_log` all reflect the built connector and the agent's calls.
Conclusion: what an agent builds and does IS surfaced in the data layer Studio reads. (UI render
layer is exercised separately by dev/e2e/test_layer3_studio_ui.py.)
