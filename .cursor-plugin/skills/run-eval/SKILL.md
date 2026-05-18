---
name: run-eval
description: Run Elliot eval suites to validate connector tool quality. Use when the user wants to test their connector against expected outputs, check token budgets, or verify tool correctness.
argument-hint: "[connector-slug or eval-file]"
when_to_use: Trigger when user says "run eval", "test my connector", "check quality", "validate tool outputs", or similar.
allowed-tools: Bash mcp__elliot__*
---

# Run Eval Workflow

## Available eval suites
!`ls connectors/*.eval.yaml 2>/dev/null || echo "(no eval suites found — see example at connectors/my-saas.eval.yaml)"`

## Steps

### 1. Find or create the eval suite
If an `*.eval.yaml` exists for the connector, call `elliot_run_eval` with its path.

If none exists, offer to create one. An eval case looks like:
```yaml
name: My Connector Evals
connector: my-connector
version: "1.0.0"
cases:
  - id: list-items-no-filter
    tool_id: list_items
    arguments: {}
    expect:
      no_error: true
      min_rows: 1
      fields_present: [id, name]
      max_token_estimate: 500
```

### 2. Read results
For each failing case:
- `no_error: false` — tool threw an error. Fix the source or SQL.
- `min_rows` not met — check if the source has data and filters are correct.
- `fields_present` failed — column name mismatch. Fix `return_fields` or rename in `response_shape`.
- `max_token_estimate` exceeded — add LIMIT or reduce return fields.

### 3. Fix and re-run
After fixing a tool via `elliot_update_tool`, re-run `elliot_run_eval`.
Repeat until all cases pass.

### 4. Check quality score
Call `elliot_quality_scan` for a full connector quality report.
Target: score ≥ 80 before deploying to production.
