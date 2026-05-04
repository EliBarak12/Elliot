# Elliot — CLAUDE.md

## Project Mission

Elliot is a platform that turns **existing products into agentic products**.

The target user is a product engineer who has a working API or database today and wants AI agents to interact with it natively — with minimum tokens, clean error recovery, and full observability. Elliot provides the tools to design, validate, deploy, and observe agent-ready tool sets built around any API or DB.

The five principles that drive every technical decision:
1. Tool descriptions are contracts — verb-first, unambiguous, typed
2. Results are sized for context windows — not raw table dumps
3. Errors are actionable — agents must know what to do next
4. Every agent session is observable — token cost, latency, errors, all visible
5. The platform itself is agentic — agents can build connectors through Elliot

See `docs/agentic-product-design.md` for the full design philosophy.

---

## Before Every Push — Mandatory Checks

All of the following must pass before any `git push`. No exceptions.

```bash
# Python — lint + type check
uv run ruff check .
uv run mypy packages/

# Python — unit + integration tests (all packages)
uv run pytest --tb=short

# TypeScript — lint
pnpm --filter elliot-studio lint

# TypeScript — tests
pnpm --filter elliot-studio test --run
```

If any command fails:
- Fix the issue first
- Re-run the full check suite from the top
- Only push when all four pass cleanly

Do **not** use `--no-verify`, `ruff --fix` without reviewing changes, or `// @ts-ignore` to force a pass.

---

## Branch Strategy

Every epic and every task gets its own branch. The hierarchy mirrors the folder structure.

### Structure

```
main
└── epic/01-monorepo-setup
    ├── task/001-monorepo-workspace       ← branch from epic branch
    ├── task/002-python-tooling
    ├── task/003-typescript-tooling
    └── task/004-package-stubs
└── epic/02-core-library
    ├── task/005-core-type-definitions
    └── ...
└── epic/03-mcp-plugin
    └── ...
...
```

### Rules

1. **Starting an epic** — create the epic branch from `main`:
   ```bash
   git checkout main && git pull origin main
   git checkout -b epic/01-monorepo-setup
   git push -u origin epic/01-monorepo-setup
   ```

2. **Starting a task** — create the task branch from its epic branch:
   ```bash
   git checkout epic/01-monorepo-setup
   git checkout -b task/001-monorepo-workspace
   git push -u origin task/001-monorepo-workspace
   ```

3. **Completing a task** — after all checks pass, merge the task branch back into its epic branch:
   ```bash
   git checkout epic/01-monorepo-setup
   git merge --no-ff task/001-monorepo-workspace
   git push origin epic/01-monorepo-setup
   ```

4. **Completing an epic** — after all tasks in the epic are merged and checks pass, merge the epic branch into `main`:
   ```bash
   git checkout main
   git merge --no-ff epic/01-monorepo-setup
   git push origin main
   ```

5. Never commit directly to `main`.
6. Never merge a task branch with failing checks.

---

## Task Completion Protocol

When a task is fully implemented, tested, and merged:

1. **Rename the task file** by adding the `complete-` prefix:
   ```
   tasks/01-monorepo-setup/001-monorepo-workspace.md
   →
   tasks/01-monorepo-setup/complete-001-monorepo-workspace.md
   ```

2. Commit the rename on the epic branch (not on the task branch):
   ```bash
   git mv tasks/01-monorepo-setup/001-monorepo-workspace.md \
           tasks/01-monorepo-setup/complete-001-monorepo-workspace.md
   git commit -m "chore(tasks): mark 001-monorepo-workspace complete"
   ```

3. The `complete-` prefix is the single source of truth for what is done. Scanning `tasks/` for files without the prefix tells you exactly what is left.

---

## Task Workflow — Step by Step

For every task, follow this sequence:

```
1.  Read the task file in full before writing any code.
2.  Create the task branch from its epic branch.
3.  Implement only what the task specifies — no extra features.
4.  Write unit tests as part of the same commit (not after).
5.  Run the full check suite (see "Before Every Push" above).
6.  Fix any failures — repeat until all pass.
7.  Push the task branch.
8.  Merge the task branch into the epic branch.
9.  Rename the task file with the `complete-` prefix.
10. Commit the rename on the epic branch.
11. Push the epic branch.
```

---

## Logging — Required Everywhere

Every module that does meaningful work must emit structured logs. Logging is not optional — it is how the developer sees what the system is doing in production.

### Python — use `structlog`

Every Python module gets a module-level logger:

```python
import structlog
log = structlog.get_logger(__name__)
```

**Log at every significant boundary:**

```python
# Service startup
log.info("service.started", port=3001, connector=config.slug)

# Incoming request (middleware handles this automatically via RequestLoggingMiddleware)
# log.info("request.received", method="POST", path="/mcp", correlation_id=cid)

# Tool call start + finish
log.info("tool.call.start", tool_id=tool_id, session_id=session_id)
log.info("tool.call.complete", tool_id=tool_id, rows=len(result), duration_ms=ms, tokens=est)

# Tool call error
log.error("tool.call.error", tool_id=tool_id, error=str(exc), error_code=exc.code)

# Connector load
log.info("connector.loaded", slug=config.slug, tools=len(config.tools), sources=len(config.sources))

# Cache events
log.debug("connector.cache.hit", slug=slug)
log.info("connector.cache.miss", slug=slug, reason="mtime_changed")

# Session lifecycle
log.info("session.opened", session_id=sid, agent_hint=hint)
log.info("session.closed", session_id=sid, total_calls=n, total_tokens=t, errors=e)

# Secrets resolution
log.info("secrets.resolved", count=n)  # NEVER log the secret values themselves

# DB / observation store
log.debug("observation.written", tool_id=tool_id, rows=row_count)
log.info("observations.pruned", deleted=n)
```

**Log levels:**
| Level | When to use |
|---|---|
| `DEBUG` | Cache hits, individual DB writes, internal state changes |
| `INFO` | Service start/stop, connector load, tool call complete, session open/close |
| `WARNING` | Recoverable issues: connector reload failed (using cached), rate limit approaching |
| `ERROR` | Tool call failed, connector load failed, auth rejected, unhandled exception |

**Never log:**
- Secret values, API keys, passwords, bearer tokens
- Raw SQL query results (they may contain PII)
- Full request/response bodies unless `LOG_LEVEL=DEBUG` and explicitly opted in

### TypeScript — use `console` with structure

In the Studio (browser), use structured console calls:
```ts
console.info('[mcp-client] connected', { url, transport: 'streamable-http' })
console.error('[tool-call] failed', { toolId, error: err.message })
console.warn('[session-poll] server unreachable, retrying', { attempt })
```

Prefix every log with the module name in brackets so they are filterable in DevTools.

---

## Error Handling — Required Everywhere

Every error that can happen must be caught, classified, logged, and returned in a structured form. An unhandled exception that reaches an agent as a 500 with no body is a bug.

### The rule: no bare `except` or silent failures

```python
# BAD — hides the error, agent gets nothing
try:
    result = executor.execute(tool, args)
except Exception:
    return []

# GOOD — classified, logged, structured response
try:
    result = executor.execute(tool, args)
except ToolNotFoundError as exc:
    log.warning("tool.not_found", tool_id=tool_id)
    raise  # let error middleware convert to 404
except SourceFetchError as exc:
    log.error("source.fetch.failed", tool_id=tool_id, url=exc.url, status=exc.status)
    raise  # let error middleware convert to 502
except Exception as exc:
    log.error("tool.call.unexpected", tool_id=tool_id, error=str(exc), exc_info=True)
    raise ElliotError("INTERNAL_ERROR", "Unexpected error during tool execution") from exc
```

### Error class hierarchy

All errors inherit from `ElliotError` (task 052). The code prefix determines the HTTP status:

```
ElliotError
├── ValidationError       (code: VALIDATION_*)  → 400
├── AuthError             (code: AUTH_*)        → 401
├── NotFoundError         (code: NOT_FOUND_*)   → 404
├── SourceFetchError      (code: SOURCE_*)      → 502
├── ConnectorLoadError    (code: CONNECTOR_*)   → 500
├── RateLimitError        (code: RATE_LIMIT_*)  → 429
└── InternalError         (code: INTERNAL_*)    → 500
```

### What every error response must include

```json
{
  "error": {
    "code": "VALIDATION_INVALID_SPECIES",
    "message": "species must be one of: dog, cat, bird, fish",
    "details": { "valid_values": ["dog", "cat", "bird", "fish"] }
  }
}
```

Agents read the `code` to decide whether to retry, try different arguments, or give up. The `message` tells them what went wrong. The `details` gives them machine-readable context to fix the call.

### Errors must never leak internals

```python
# BAD — leaks DB schema, file paths, stack traces to the agent
{"error": "psycopg2.OperationalError: column \"usr\" does not exist at character 8"}

# GOOD — structured, actionable, safe
{"error": {"code": "SOURCE_QUERY_FAILED", "message": "Database query failed. Check connector SQL."}}
```

The full stack trace goes to the log (`log.error(..., exc_info=True)`). The agent only sees the structured error.

### TypeScript — all fetch calls must handle errors

```ts
// Every API call in Studio wraps errors before surfacing to UI
async function callTool(toolId: string, args: Record<string, unknown>) {
  try {
    const res = await fetch(`${RUNTIME_URL}/mcp`, { ... })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ElliotClientError(body?.error?.code ?? 'UNKNOWN', body?.error?.message ?? res.statusText)
    }
    return await res.json()
  } catch (err) {
    console.error('[tool-call] failed', { toolId, error: err })
    throw err  // re-throw so the UI component can show the error state
  }
}
```

The UI must always show a human-readable error state — never a blank panel or a silent no-op when a call fails.

---

## Code Standards

### Python
- All public functions and classes have type annotations
- Pydantic models for all data structures that cross a service boundary
- No `Any` in public interfaces unless unavoidable and documented
- `structlog` for all logging — never `print()` or bare `logging.info()`
- All errors inherit from `ElliotError` in `elliot_core.errors`
- Secrets never in logs, never in API responses, never hardcoded — use `{{ env:VAR }}` in connector files

### TypeScript
- Strict mode on (`"strict": true` in tsconfig)
- No `any` — use `unknown` and narrow
- All fetch calls go through `src/client/http.ts` so the API key header is always injected

### Tests
- Unit tests live next to the code they test or in a `tests/` folder at the package root
- Integration tests that require a running service are marked `@pytest.mark.integration` and skipped in unit-only runs
- Coverage gates (enforced in CI): `elliot-core` ≥ 95%, `elliot-mcp-plugin` ≥ 85%, `elliot-connector-runtime` ≥ 85%, `elliot-studio` ≥ 70%
- Every task file includes a Tests section — implement all cases listed there
- **Every error path must have a test.** If a function can raise, there must be a test that triggers that raise and asserts the correct error code and log output.

### Commits
- Format: `type(scope): short description`
- Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`
- Scope is the package or area: `core`, `plugin`, `runtime`, `studio`, `tasks`, `docs`
- Example: `feat(runtime): add multi-connector directory mode`

---

## Project Structure Quick Reference

```
elliot/
├── packages/
│   ├── core/                   # elliot-core (shared Python library)
│   ├── mcp-plugin/             # elliot-mcp-plugin (:3000)
│   ├── connector-runtime/      # elliot-connector-runtime (:3001)
│   └── studio/                 # elliot-studio (React :5173)
├── tasks/                      # Task specs (rename to complete-* when done)
├── docs/                       # Architecture, product, user stories
├── connectors/                 # User connector.json files
├── templates/                  # Starter connector templates
├── .elliot/                    # Runtime data (observations.db, logs)
├── Procfile                    # Local dev: honcho start
├── docker-compose.yml          # Production: docker compose up
└── .env.example                # All env vars documented
```

## Key Ports

| Service | Port | Start command |
|---|---|---|
| `elliot-mcp-plugin` | 3000 | `uv run uvicorn elliot_mcp_plugin.server:app` |
| `elliot-connector-runtime` | 3001 | `uv run uvicorn elliot_connector_runtime.server:app` |
| `elliot-studio` | 5173 | `pnpm --filter elliot-studio dev` |
| All together | — | `honcho start` |

## Key Env Vars

| Variable | Default | Purpose |
|---|---|---|
| `ELLIOT_API_KEY` | *(unset = no auth)* | Protect all endpoints |
| `ELLIOT_CONNECTORS_DIR` | `./connectors` | Directory of connector.json files |
| `ELLIOT_DB_URL` | `sqlite:///.elliot/observations.db` | Observation store (set to MySQL URL for remote) |
| `ELLIOT_RATE_LIMIT` | `120/minute` | Per-IP rate limit on tool endpoints |
| `LOG_LEVEL` | `INFO` | structlog output level |

See `.env.example` for the full list.
