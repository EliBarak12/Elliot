# CLI

Every Elliot operation has a CLI command. The same commands are exposed to agents as MCP tools — anything you can run, an agent can run.

## `elliot init`

Scaffold a new connector from a template.

```bash
elliot init --template rest-api-key my-api.connector.json
```

Templates:

- `rest-api-key` — REST API with API key header auth
- `postgres-readonly` — PostgreSQL read-only connector
- `paginated-rest` — REST API with cursor/offset pagination
- `openapi-petstore` — full Petstore example (docs/tutorials)

Run `elliot init --list` to print this list.

## `elliot lint`

Validate a connector against the schema and the [five principles](./five-principles).

```bash
elliot lint my-api.connector.json
```

Exit code is non-zero on any failure. CI-friendly.

## `elliot eval`

Run an eval suite and report pass/fail with row counts and token estimates.

Eval is **deterministic** — there is no LLM involved. Each case names a tool
and the arguments to call it with; Elliot executes that tool directly against
the connector and asserts on the result (row counts, fields present, token
size, error codes). This makes eval fast, free, and reproducible in CI.

```bash
elliot eval my-api.eval.yaml
```

An eval suite has a `name`, the `connector` it targets, and a list of `cases`.
Each case has an `id`, a `tool_id`, the `arguments` to call it with, and an
`expect` block of assertions:

```yaml
name: My SaaS Analytics
connector: my-saas
version: "1.0.0"
cases:
  - id: list-customers-by-plan
    description: Filters to only pro-plan customers
    tool_id: list_customers
    arguments: { plan: pro }
    expect:
      no_error: true
      min_rows: 1
      fields_present: [id, name, email, plan]
      max_token_estimate: 800
      all_rows_match: { field: plan, value: pro }
```

Supported `expect` keys: `no_error` (default `true`), `min_rows`, `max_rows`,
`fields_present`, `all_rows_match` (`{ field, value }`), `error_code`, and
`max_token_estimate`. See `connectors/my-saas.eval.yaml` in the repo for a
complete working suite.

## `elliot connect`

Auto-register Elliot with every coding agent on the host.

```bash
elliot connect
```

Detects Claude Code, Cursor, OpenClaw, and Codex and writes the right MCP config for each. Re-run any time you install a new agent.

## `elliot status`

Show the health of plugin, runtime, and Studio.

```bash
elliot status
```

```
elliot-mcp-plugin       :3000   ✓ healthy
elliot-connector-runtime :3001  ✓ healthy
elliot-studio            :5173  ✓ healthy
```

## `elliot deploy`

Push a connector into the running runtime (or a hosted runtime).

```bash
elliot deploy my-api.connector.json
```

## Same commands, agentic edition

Each of the above is registered with the MCP server as a tool with a verb-first description. An agent inside Claude Code can run `lint-connector` and `run-eval` against a connector it just wrote — without leaving the chat.
