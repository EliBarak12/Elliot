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
`elliot_lint_connector` lints the connector currently built in the session and
takes no arguments. If nothing has been built yet, call `elliot_build_connector`
first (use `elliot_list_tools` to see what tools are registered). To lint an
existing connector file, load it into the session and build it before linting.

### 2. Read every issue
For each issue reported:

| Severity | Action |
|----------|--------|
| `error` | Must fix — connector won't pass validation |
| `warning` | Should fix — hurts agent accuracy |
| `info` | Optional — quality improvement |

### 3. Fix the issues by code

The linter emits stable UPPER_SNAKE codes (the exact strings you'll see in the
output). The common ones and how to fix them:

| Code | Severity | Fix |
|------|----------|-----|
| `DESCRIPTION_TOO_SHORT` | error | Write ≥15 chars: `"<Verb> <object>. Use when <context>. Returns <fields>. <constraint>."` |
| `DESCRIPTION_MISSING_VERB` | warn | Start the description with a verb — "Return…", "List…", "Create…", "Count…". |
| `UNBOUNDED_SELECT` | error | A `SELECT *` with no `WHERE` or `LIMIT`. Add `LIMIT :limit` or a filter parameter. |
| `SELECT_STAR_NO_LIMIT` | warn | Replace `SELECT *` with an explicit column list, or add a `LIMIT`. |
| `MISSING_PAGINATION` | warn | List-style READ tool with no LIMIT/cursor — add `LIMIT :limit` or a limit/offset/cursor parameter. |
| `PARAMETER_NAME_GENERIC` / `_TOO_SHORT` | warn | Rename to something specific: `customer_id`, `order_status`. |
| `PARAMETER_MISSING_DESCRIPTION` | warn | Add a description so agents know what to pass. |
| `PARAMETER_SHOULD_BE_ENUM` | warn | Declare the fixed value set as an `enum`. |
| `FILTER_SEMANTICS_UNCLEAR` | warn | In the *parameter's own* description, state exact / contains / prefix / case-insensitive matching. |
| `WRITE_TOOL_DESCRIPTION` | info | Add the mutation verb ("Creates…", "Deletes…") to a WRITE/ACTION tool. |
| `SENSITIVE_FIELD_EXPOSED` | error | A field the product intent marked never-expose appears in this tool's SQL/output **or** its forwarded `rest_query_params` / `api_mapping` body/query params. Drop or redact it. |
| `SECRET_IN_URL` | error | A secret is embedded in `source.url`. Move it to `auth.secret_key` as `{{ env:VAR }}`. |

Auth issues (these fire on the *source*, not a tool):

| Code | Severity | Fix |
|------|----------|-----|
| `AUTH_OAUTH2_MISSING_CONFIG` | error | `auth.type: "oauth2"` needs an `oauth2` block (authorization_url, token_url, client_id_secret, client_secret_secret). |
| `AUTH_OAUTH2_CLIENT_NOT_ENV` | warn | OAuth `client_id_secret` / `client_secret_secret` must be `{{ env:VAR }}`, never a literal. |
| `AUTH_PER_USER_SLOT_IS_ENV` | warn | A `scope: "per_user"` source's `secret_key` should be the per-user slot (e.g. `access_token` / `{{ user_oauth:ID }}`), not `{{ env:VAR }}`. |
| `AUTH_LITERAL_SECRET` | warn | A shared-auth `secret_key` looks like a literal credential — use `{{ env:VAR }}`. See `elliot://docs/authentication`. |

If you see a code not listed here, read its `message` and `suggestion` — every
issue carries actionable recovery text. Don't guess from the code name alone.

### 4. Re-lint
After editing tools with `elliot_update_tool`, call `elliot_build_connector`
to rebuild, then `elliot_lint_connector` again. Repeat until zero errors and
zero warnings.

### 5. Export
Call `elliot_export_connector` to persist the fixes to disk.

## Debugging tools

When a tool's SQL fails or returns the wrong shape, use these before guessing:
- `elliot_profile_source(table_name)` — min/max/null/distinct/top-5 for every
  column. Tells you whether your WHERE clause is over-filtering or your enum
  values are stale.
- `elliot_profile_column(table_name, column_name)` — same stats for one column.
- `elliot_explain_query(sql)` — SQLite `EXPLAIN QUERY PLAN` output. Use when
  a tool is slow or you're worried about a missing index.
- `elliot_validate_sql(sql)` — syntax + safety check without executing.

## Quality bar
A production-ready connector has:
- Zero lint errors
- Zero lint warnings
- Every tool description starts with a verb and says what it returns
- No tool returns more than 1000 tokens on average
