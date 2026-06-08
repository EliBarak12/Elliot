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

### [BUG-3 — FIXED] Optional params with defaults bind NULL at runtime → agents can't use "top N" tools (HIGH)
Found by sending an agent to USE 10 deployed connectors. The agent calls a tool with only its
required args (the normal pattern), omitting optional params. For the extremely common
"list top N (default N)" shape (`... ORDER BY x DESC LIMIT :limit`, limit optional default 5),
the call failed with `[INVALID_SQL] datatype mismatch`. 6 of the 10 connectors hit this.
- Root cause: the connector-runtime `ToolExecutor` bound SQL params with
  `{p.name: arguments.get(p.name) for p in tool.parameters}` — the param default was never
  applied. Subtlety that made it hard to see: the MCP layer passes an *omitted* optional param as
  an explicit `None` (the property is declared in the input schema), so even
  `arguments.get(name, default)` returns `None`. Binding `None` to `LIMIT :limit` → SQLite
  "datatype mismatch". The same latent bug existed in elliot_core's `_coerce_and_validate`
  (used by eval_runner, eval_tools, skill_tools, and the plugin MCP server).
- Fix: both binders now coalesce missing-key AND explicit-None to the declared default
  (`_bind_sql_params` in connector-runtime; `_coerce_and_validate` in elliot_core). Added
  unit + execute-level regression tests in both packages. (`preview_tool` already coalesced
  correctly, which is why the build-time previews passed and masked this.)
- Verified: AGENT run — 10/10 connectors deployed, 17/17 agent tasks pass (was 8/17).

### [AGENTS] 10 connectors built + used by an agent — 17/17 tasks PASS (after BUG-3 fix)
Built 10 real connectors (jsonplaceholder blog/todos/photos, dummyjson products/carts,
restcountries, pokeapi, coingecko, catfact, open-meteo) and turned a schema-driven agent loose:
for each NL task it selects a tool from its description, fills params from the input schema, calls
it, and the result is verified. Exercises tool-selection, parameter inference, nested-array JOINs,
aggregates, filters, and single-object endpoints. All pass.

### [OBS-5] coingecko runtime materialization can 429 (environmental, not a bug)
During one run, coingecko's free API rate-limited at runtime materialization → TABLE_NOT_FOUND.
The runtime surfaced a clear, actionable error and stayed healthy. Re-running (or a paid key)
resolves it. Noted so it isn't mistaken for a product defect.

### [CHAINS] Multi-step agent chains — 3/3 PASS (tools compose)
Tested whether an agent can chain tools: call A, take a value from A's result, feed it to B.
This only works if A's output exposes the field B needs (principle #2 — results shaped for the
next step). All three real chains pass:
- c01: find_user_by_name("Leanne Graham") -> id=1 -> list_posts_by_author(1) -> 10 posts, all userid=1.
- c02: product_categories() -> "beauty" -> products_in_category("beauty") -> 5 products, all beauty.
- c10: photo_count_per_album() -> busiest album 100 -> photos_in_album(100) -> 50 photos, all album 100.
Confirms tool outputs carry the ids/keys needed to drive the next call. (Note: the harness's
heuristic agent fills params by name then by type; chains are written so the needed value can only
come from the previous step, making each a real composition test.)

### [UI] Studio renders what agents build — verified in a real browser
Installed Playwright Chromium and ran the repo's layer-3 Studio e2e (PASS) plus a new
`studio_screenshots.py` that boots the full stack, seeds a connector via MCP, deploys it, has two
consumer agents call its tools, then screenshots all Studio pages with real data:
- Dashboard: 5 sources / 5 tools / 1 skill, "Connector Live", "What your agent has built" 100%,
  Recent activity listing real tool invocations with row counts + latency.
- Metrics: Total Calls 6, Error Rate 0.0%, Avg Latency 24ms, top-tools chart, per-tool
  calls/success/latency table.
- Agent Console / Tools / Connector / Sources / Skills all render the agent-built state.
Conclusion: the UI surfaces everything an agent builds and does — confirmed visually, not just at
the data layer. Screenshots saved under dev/e2e/launch_gateway/screenshots/ (gitignored).

### [SEC+AGENTIC] Secret hygiene + agentic build-loop — 7/7 PASS
- Auth source fetched via `{{ env:REVIEWS_TOKEN }}` resolution (rows=5).
- LAUNCH-CRITICAL: exported connector keeps the `{{ env:VAR }}` template and does NOT contain the
  resolved secret value — connector files are safe to commit (no key leak).
- quality_scan: well-formed tool 100.0 vs deliberately weak tool ("data"/"get data"/SELECT *) 80.0,
  overall 90.0 with the weak tool flagged — the quality differentiator works.
- run_eval: suite executes against live tools, score 100, 1 passed.

---

## SUMMARY (launch gateway)
3 real bugs found and FIXED (all with regression tests, all pushed):
- BUG-1 (HIGH): deep-nesting INVALID_IDENTIFIER crash in discovery — flattener now bounds identifiers.
- BUG-2 (MED): build_connector silently built empty connector for unknown tool_ids — now validates.
- BUG-3 (HIGH): optional param defaults bound NULL at runtime ("list top N" broke for agents) — both
  executors now coalesce missing/None to the declared default.
Coverage proven end-to-end: 17 real-API build scenarios, 10 connectors used by an agent (17/17
tasks), 3 multi-step tool chains, full observability loop, Studio UI render (real browser),
negative/security paths, secret hygiene, and the eval/quality agentic features. Mandatory suite
green throughout (1141 tests).

---

## REAL AGENTS (not scripts) — builder agents build, consumer agents use

The earlier harnesses spoke Elliot's MCP protocol exactly like an agent but chose tools/params with
heuristic Python. This section uses **real Claude agents** (the authenticated `claude` CLI with
`--mcp-config`, reasoning autonomously and calling Elliot's MCP tools).

### LOCAL Elliot
- Booted the plugin (builder MCP at :3000) in a clean workspace.
- **Builder agent** (real `claude -p`, MCP=elliot): given a product-engineer prompt, it discovered
  3 jsonplaceholder sources (posts/users/comments), created 3 verb-first tools
  (list_posts_by_user, get_post_comments, look_up_user), built + exported + started the runtime at
  http://localhost:3001/mcp/ — all via Elliot MCP tools, its own decisions.
- **Consumer agent** (real `claude -p`, MCP=the deployed runtime): given only natural-language
  questions, it inspected the tools and answered correctly (user 1 → 10 posts; username 'Bret' →
  Leanne Graham / Sincere@april.biz / Romaguera-Crona; post 1 → 5 comments).
- Runtime observability recorded the consumer agent's session + per-tool token/latency metrics.

### ELLIOT CLOUD (multi-tenant, apps/api)
- Ran cloud venv against the FIXED local elliot packages; `pytest` → 107 passed.
- Booted the Cloud API (dev-mode auth via X-Dev-Email, sqlite). Dev user auto-provisioned an org.
- Issued a builder token (POST /api/me/builder-tokens) → Cloud builder MCP at /b/mcp.
- **Builder agent** (real `claude -p`, MCP=Cloud /b/mcp with Bearer token): discovered
  restcountries/region/europe (53 countries), created 2 tools (list_most_populous_countries with
  optional limit, lookup_country_by_name), built the connector, and **published it to the cloud**
  via the `elliot_cloud_publish` MCP tool → public URL http://localhost:8000/c/<id>/mcp/.
- Minted a per-connector consumer API key (POST .../keys).
- **Consumer agent** (real `claude -p`, MCP=the published Cloud URL + X-Elliot-Key): answered with
  live data — top-5 populous European countries (Russia, Germany, UK, France, Italy) and France →
  Paris / 66,351,959. (The "top 5" call exercised the optional-limit tool — i.e. the BUG-3 fix on
  the cloud runtime.)
- Security verified: published URL with no key → 401, wrong key → 401, cross-tenant GET → 404
  (does not reveal existence). Cloud observability recorded 2 tool calls with per-tool metrics.

Conclusion: real agents BUILD connectors and real (separate) agents USE them — proven end-to-end on
both local Elliot and the multi-tenant Elliot Cloud, including publish, per-connector API-key auth,
tenant isolation, and observability.

---

## REAL-USER SIMULATION: Stripe-like product API, real agents, trace-driven fixes

Scenario: a SaaS founder with a substantial billing/product API wants to make it agentic via
Elliot + Claude Code, publish, and watch how agents fare. Used a purpose-built, realistic
Stripe-like API (140 customers, 154 subscriptions, 670 invoices, 592 charges; cents, unix ts,
status enums, nested objects, foreign keys, cursor pagination) — not a toy mock.

Method: REAL Claude agents (authenticated `claude` CLI + `--mcp-config`), full stream-json traces
captured and analyzed. Iterated build → analyze trace → fix Elliot → rebuild → verify.

### Builder-agent trace findings + fixes
1. [FIXED] `elliot_create_tool` `category` ambiguity — the agent passed business domains
   ("Subscriptions", "Revenue") and hit "Unknown category" 6× in one build. Documented the access-type
   enum (read/aggregate/write/action) in the tool description. v4: 0 category errors.
2. [FIXED] Silent partial data — discovery fetched only the first page (10 of 140) with no signal.
   Added a warning when a response advertises more pages (has_more / next_cursor / Link rel=next) but
   no pagination is configured. v2+: the agent saw it and configured pagination.
3. [FIXED — architectural] Pagination was DUPLICATED in api_fetcher (design-time) and the
   connector-runtime executor (call-time) and had diverged; a discovery-only fix would NOT reach the
   deployed runtime. Extracted ONE shared engine (elliot_core.sources.pagination) used by both, and
   generalized cursor config (cursor_param, cursor_record_field, has_more_field) so Stripe-style
   (?limit=&starting_after=<last id> + has_more) is declarative, not special-cased. (Per reviewer
   guidance: a proper fix aligned across all architectures, not a one-use-case patch.)
   Verified: deployed runtime fetches all 140 customers; total_paid_revenue = 553 paid invoices /
   $118,704 (was computing from ≤10 before).

### Iteration result (v1 → v4, same prompt)
- v1: 67 turns, 10 errors, 6 category failures, silent 10-row data.
- v4 (after fixes): 55 turns, 0 category errors, 0 pagination-config rejections, agent configured
  cursor pagination, connector serves COMPLETE data.

### 3 consumer agents (real) on missions against the deployed connector — all succeeded, 0 real errors
- Finance: "$118,704 paid revenue across 553 invoices; 66 uncollectible/void; 65 delinquent."
- Support: drilled into a delinquent customer (Noah Tanaka), listed invoice history, found $897 bad debt.
- Ops: "123 active subscribers; $8,406 actionable failed-payment exposure; top reason card_declined."
Studio UI screenshots captured showing Dashboard (Connector Live, 66/65-row results — complete data),
Metrics (12 calls, 0% errors, per-tool latency), Tools, Connector, Console.

### [OBS-6 — INVESTIGATED, NO FIX WARRANTED] Agent guessed resource URIs
Across builds the agent tried `resources/read elliot://prompt/getting_started` / `elliot://principles`
(guesses) → "Unknown resource", then recovered instantly (zero outcome impact). On inspection this is
NOT an Elliot defect: the server's onboarding instructions ALREADY tell the agent to call
`resources/list` and name the available resources (principles, error-codes, install), and getting_started
is correctly served as a prompt (`prompts/get name=getting_started`). The agent guessed a URI instead of
listing. Adding alias resources to match guesses would be a one-use-case patch for a non-bug, so —
consistent with the "proper fix, not patch" standard — no code change was made.

---

## ELLIOT CLOUD: full real-agent loop with the OSS fixes (build → publish → consume)

Ran the same Stripe-like billing scenario on the multi-tenant Cloud platform (apps/api), with the
Cloud venv using the FIXED local OSS packages (editable). Restarted the Cloud API to load the fixes
+ ELLIOT_SSRF_ALLOW_PRIVATE so it could reach the local billing API.

- Dev-mode org bootstrapped; issued a builder token; **real builder agent** connected to Cloud
  `/b/mcp` and built the "Billing API" connector, configured Stripe cursor pagination
  (cursor_param/cursor_record_field/has_more_field), and **published** it via `elliot_cloud_publish`
  → public URL `http://localhost:8000/c/<id>/mcp/`. (0 category errors, 0 pagination-config
  rejections — the OSS fixes carried over to Cloud.)
- Minted a per-connector API key. Verified the **published Cloud connector serves COMPLETE data**
  through the multi-tenant runtime: count_active_subscribers returns full per-tier aggregates
  (42 scale + 31 enterprise + 24 growth + ...), not a 10-row first page. => the shared pagination
  engine works on Cloud.
- **3 real consumer agents** (finance/support/ops) against the PUBLISHED Cloud URL + API key — all
  succeeded: $118,704 collected / $5,615 write-off exposure / 28 delinquent (finance); per-customer
  invoice drill-down (support); 114 active subs / 15 past_due / expired-card recovery (ops).
- Cloud per-connector observability: 11 calls, 0.0 error_rate, 33ms avg, per-tool breakdown.

### [CLOUD-FIX] cursor_record_field not discoverable upfront → fixed in the template
The Cloud builder agent took many retries (tried cursor_field, cursor_param, JMESPath) before the
post-fetch warning revealed cursor_record_field. Proper, general fix (not a use-case patch): the
`paginated-rest` connector template now demonstrates BOTH cursor idioms — top-level `cursor_field`
AND Stripe-style `cursor_param`/`cursor_record_field`/`has_more_field` — so the fields are
discoverable from the reference material agents read (resources/read
elliot://templates/paginated-rest), before any failed fetch.
