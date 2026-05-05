# 051 — Evaluation Page UI

**Sprint**: 4 | **Estimate**: 3h | **Depends on**: 050

## Objective
Full evaluation UI: create test suites, run them, view scores, detect regressions.

## Files to Create

### `src/pages/EvaluationPage.tsx`
Two tabs: **Eval Suites** and **Quality Scan**

**Eval Suites tab:**
- List of eval suites with last score badge
- "New Suite" button → opens `EvalSuiteEditor`
- "Run" button per suite → calls `callTool('elliot_run_eval', { suiteId })` → shows progress
- Results panel: overall score gauge, per-case table (pass/fail/error)
- Score history mini-chart (last 5 runs)
- Regression badge: red count of cases that regressed since last run

**Quality Scan tab:**
- "Run Scan" button → calls `callTool('elliot_quality_scan', {})` → shows results
- Per-tool quality card: score badge + list of failing checks
- Fix suggestions inline

### `packages/mcp-plugin/src/elliot_mcp_plugin/tools/eval_tools.py`
Two new MCP tools registered in `create_elliot_server`:
- `elliot_run_eval`: `{ suite_id }` → load suite from `.elliot/eval/`, run via `run_eval_suite()`, save result, return `EvalRunResult`
- `elliot_quality_scan`: — → run `analyze_connector_quality()` on current session connector, return `ConnectorQualityScore`

## Done When
- [ ] Eval suite can be created and run from UI
- [ ] Score displayed correctly after run
- [ ] Regression badge shows when a previously-passing case now fails
- [ ] Quality scan shows per-tool issues
