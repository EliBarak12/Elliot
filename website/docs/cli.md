# CLI

Every Elliot operation has a CLI command. The same commands are exposed to agents as MCP tools — anything you can run, an agent can run.

## `elliot init`

Scaffold a new connector from a template.

```bash
elliot init --template rest-api-key my-api.connector.json
```

Templates: `rest-api-key`, `rest-bearer`, `postgres`, `mysql`, `csv-local`.

## `elliot lint`

Validate a connector against the schema and the [five principles](./five-principles).

```bash
elliot lint my-api.connector.json
```

Exit code is non-zero on any failure. CI-friendly.

## `elliot eval`

Run an eval suite — real prompts through real agents — and report pass/fail with token counts.

```bash
elliot eval my-api.eval.yaml
```

Eval files look like:

```yaml
suite: pet store
cases:
  - prompt: "How many cats do we have?"
    expect_tool: list_animals
    expect_args: { species: "cat" }
```

## `elliot connect`

Auto-register Elliot with every coding agent on the host.

```bash
elliot connect
```

Detects Claude Code, Cursor, VS Code Copilot, Windsurf, and Codex and writes the right MCP config for each. Re-run any time you install a new agent.

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
