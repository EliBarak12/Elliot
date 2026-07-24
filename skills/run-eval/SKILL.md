---
name: run-eval
description: Run Elliot eval suites to validate connector tool quality. Use when the user wants to test their connector against expected outputs, check token budgets, or verify tool correctness.
argument-hint: "[connector-slug or eval-file]"
when_to_use: Trigger when user says "run eval", "test my connector", "check quality", "validate tool outputs", or similar.
allowed-tools: Bash mcp__elliot__*
---

# Run Eval Workflow

## Available eval suites
!`ls connectors/*.eval.yaml .elliot/eval/*.json 2>/dev/null || echo "(no eval suites found — see example at connectors/my-saas.eval.yaml)"`

## Steps

### 1. Find or create the eval suite

`elliot_run_eval` accepts either:
- `path` — a path to an `*.eval.yaml` (preferred) or `*.json` suite file, OR
- `suite_id` — the bare id of a JSON suite under `.elliot/eval/<id>.json`.

If a `*.eval.yaml` already lives next to the connector, call
`elliot_run_eval(path="connectors/<slug>.eval.yaml")`.

If none exists, offer to create one. The canonical shape is YAML:

```yaml
name: My Connector Evals
connector: my-connector
version: "1.0.0"
cases:
  - id: list-items-no-filter
    description: Returns at least one row with the expected fields
    tool_id: list_items
    arguments: {}
    expect:
      no_error: true
      min_rows: 1
      fields_present: [id, name]
      max_token_estimate: 500
  - id: list-items-rejects-bad-status
    description: A bad enum value is rejected, not silently ignored
    tool_id: list_items
    arguments: { status: not-a-real-status }
    expect:
      error_code: INVALID_PARAM_VALUE
```

**Cover the error paths, not just the happy path.** A tool that returns good
rows for good input but silently accepts bad input is not agent-ready — the
agent gets an empty or wrong result with no signal. Add at least one case per
tool that asserts a bad argument is *rejected*: set `expect.error_code` to the
code you expect (`INVALID_PARAM_VALUE` for a bad enum/bound, `MISSING_PARAM` for
an omitted required param, `UNKNOWN_PARAM` for a stray key). The case passes only
if the tool raises that code, and fails if the call succeeds — so you prove the
contract rejects what it should. (In a legacy JSON suite the equivalent is
`"expect_error": "INVALID_PARAM_VALUE"` on the case.)

### 2. Read results

For each failing case:
- `no_error: false` — the tool threw. Read the error message, then either
  fix the source (auth, URL, connection string) or the tool's SQL.
- `min_rows` not met — check the source actually has data
  (`elliot_preview_source` or `elliot_sample_data`) and that the tool's
  WHERE clause is not over-filtering.
- `fields_present` failed — the row keys returned by the tool don't include
  the expected column. Fix the tool's `SELECT` clause via
  `elliot_update_tool(tool_id, {"sql": "SELECT id, name, ... FROM ..."})`.
- `max_token_estimate` exceeded — add or tighten a `LIMIT` in the SQL, or
  drop columns from the `SELECT` list.

### 3. Fix and re-run

After fixing a tool via `elliot_update_tool`, call `elliot_build_connector` to
rebuild the connector, then re-run `elliot_run_eval`. Repeat until all cases
pass.

### 4. Check quality score

Call `elliot_quality_scan` for a full connector quality report. Target:
score ≥ 80 before deploying to production.
