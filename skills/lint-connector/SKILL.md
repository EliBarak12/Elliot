---
name: lint-connector
description: Lint an Elliot connector file and fix all reported issues. Use when the user wants to validate a connector, improve tool descriptions, or fix quality warnings.
argument-hint: "[connector-file or slug]"
when_to_use: Trigger when user says "lint my connector", "check my connector", "fix the warnings", "improve my tool descriptions", or similar.
allowed-tools: Bash mcp__elliot__*
---

# Lint Connector Workflow

## Connector files
!`ls connectors/*.connector.json 2>/dev/null || echo "(no connectors found)"`

## Steps

### 1. Run lint
If the user named a specific file, call `elliot_lint_connector` with that slug.
Otherwise list with `elliot_list_tools` and ask which connector to lint.

### 2. Read every issue
For each issue reported:

| Severity | Action |
|----------|--------|
| `error` | Must fix — connector won't pass validation |
| `warning` | Should fix — hurts agent accuracy |
| `info` | Optional — quality improvement |

### 3. Fix descriptions
For `description_no_verb` issues: rewrite to start with a clear verb.
Pattern: `"<Verb> <object>. Use when <context>. Returns <fields>. <Key constraint>."`

For `token_risk_high` issues: add a LIMIT parameter or reduce return fields.

For `sql_select_star` issues: replace `SELECT *` with explicit column list.

### 4. Re-lint
Call `elliot_lint_connector` again. Repeat until zero errors and zero warnings.

### 5. Save
Call `elliot_save_connector` to persist the fixes.

## Quality bar
A production-ready connector has:
- Zero lint errors
- Zero lint warnings
- Every tool description starts with a verb and says what it returns
- No tool returns more than 1000 tokens on average
