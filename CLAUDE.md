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
