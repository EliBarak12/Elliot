"""MCP resources: connector templates and reference docs surfaced over MCP.

Resources are how Elliot ships *reference material* to agents — connector
templates, the five principles, the error-code dictionary, and installation
docs. Every MCP-speaking agent can read these via `resources/list` +
`resources/read`. They're the static counterpart to prompts (which are
workflow procedures) and tools (which take action).

Source of truth for templates: `packages/core/src/elliot_core/templates/`.
Inline docs (principles, errors, install) live as constants below — they're
small, stable, and benefit from being version-pinned with the server code.
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Callable
from pathlib import Path

import structlog
from mcp.server.fastmcp import FastMCP

log = structlog.get_logger(__name__)


_PRINCIPLES_MD = """# Elliot's Five Principles

Every tool you create or modify in Elliot must honor these. They are the contract
between the connector author and the downstream agents that will call the tools.

## 1. Tool descriptions are contracts

Verb-first, unambiguous, typed. A tool description tells the agent *exactly*
what action it takes, what inputs it needs, and what shape of result it returns.

- BAD: `"Items"`
- BAD: `"Returns items from the API"`
- GOOD: `"List items owned by the current account. Filter by status with the
  optional 'status' parameter. Returns up to 50 rows; pass 'cursor' for the
  next page."`

## 2. Results are sized for context windows

Never return raw table dumps. Paginate, project, summarize. A tool that returns
500 rows of 40 columns will blow an agent's context budget on a single call.

- Always cap default page size (≤50 rows).
- Always project to only the columns the description promises.
- Include a `cursor` or `next_page_token` field if more results exist.
- For aggregations, return the aggregate, not the underlying rows.

## 3. Errors are actionable

Every error must tell the agent what to do next. An error without recovery
guidance is a dead end that wastes turns.

- `{"code": "AUTH_FAILED", "message": "API rejected the bearer token",
  "details": {"recovery": "Confirm ACME_API_KEY is set in the environment"}}`
- Never silently fail. Never `except Exception: pass`.
- Never log the secret value; log only the env-var name.

## 4. Every agent session is observable

Every tool call, token cost, latency, and error shows up in Studio. The
connector runtime writes observation records to SQLite for every call. Use
Studio to find the tools that are slow, expensive, or error-prone — then fix
their descriptions.

## 5. The platform itself is agentic

Elliot is built so that *agents* are the primary author of connectors. The
human points at an API; the agent calls `elliot_discover_source`, drafts the
tools, runs lint and eval, fixes the warnings, and deploys. The Studio
dashboard is for *watching* the agent, not driving it manually.
"""


_AUTH_MD = """# Authentication & the Runtime Fetch Model

How a connector authenticates upstream, and *when* it actually calls the
upstream, is configured per-source and per-tool — not baked once at build time.
Read this before assuming "Elliot only queries a frozen snapshot with one
shared credential." It supports live calls at tool-call time **and** per-user
auth where each caller brings their own credential.

## Common misconception (read this first)

A frequent wrong conclusion: *"Elliot loads data into SQLite at discovery time
with one credential baked in, so it can't do per-user auth or live calls."*
That is **false**. Two capabilities cover exactly that:

1. **Live fetch at tool-call time** — see "Tool execution modes" below.
2. **Per-user auth** — set `auth.scope: "per_user"`; each caller authorizes
   their own account and their token is used for their calls.

## Auth is a (type × scope) matrix

A source's `auth` block has a `type` and a `scope`.

```json
"auth": {
  "type": "bearer",          // api_key | bearer | basic | oauth2
  "scope": "shared",         // shared | per_user   (default: shared)
  "secret_key": "{{ env:ACME_TOKEN }}",
  "header_name": null,       // for type=api_key: which header carries the key
  "query_param": null        // for type=api_key: OR which query param carries it
}
```

**`type`** — how the resolved secret becomes the upstream request auth:

| type | becomes |
|------|---------|
| `bearer` | `Authorization: Bearer <secret>` |
| `oauth2` | `Authorization: Bearer <secret>` (secret is a per-user OAuth access token) |
| `api_key` | `{header_name: <secret>}` **or** `?{query_param}=<secret>` |
| `basic` | `Authorization: Basic base64("user:pass")` (secret is `"user:pass"`) |

**`scope`** — *whose* credential is used:

- **`shared`** (default): one credential, same for every caller. Put it in
  `secret_key` as `{{ env:VAR }}`. Use for public/open data or a single
  service account (e.g. `data.gov.il`, an internal reporting DB).
- **`per_user`**: each end user connects their **own** account; their token is
  resolved per-request from a per-user vault and used only for their calls.
  Use for GitHub / Slack / Gmail / any "act as the calling user" connector.

## Secret placeholders

- `{{ env:VAR_NAME }}` — a shared secret, resolved from the org vault (cloud)
  or the environment (self-hosted). Used for `scope: shared` credentials and
  for an OAuth app's own `client_id` / `client_secret`.
- `{{ user_oauth:SOURCE_ID }}` — **(Elliot Cloud)** the calling user's stored
  OAuth access token for the source whose `id` is `SOURCE_ID`. Put this in the
  `secret_key` of a `per_user` source. Auto-refreshed before expiry; raises
  `AUTH_REQUIRED` if the user hasn't connected yet.
- Never put a literal credential in a connector file. Lint rejects it.

## Per-user OAuth — the full pattern

A per-user OAuth2 source declares the **upstream provider's** endpoints plus the
connector author's (app-level) OAuth client credentials:

```json
{
  "id": "github",
  "type": "rest",
  "url": "https://api.github.com/user/repos",
  "auth": {
    "type": "oauth2",
    "scope": "per_user",
    "secret_key": "{{ user_oauth:github }}",
    "oauth2": {
      "authorization_url": "https://github.com/login/oauth/authorize",
      "token_url": "https://github.com/login/oauth/access_token",
      "scopes": ["repo"],
      "client_id_secret": "{{ env:GITHUB_CLIENT_ID }}",
      "client_secret_secret": "{{ env:GITHUB_CLIENT_SECRET }}"
    }
  }
}
```

At call time:
1. The runtime resolves the **calling user's** stored token into `secret_key`
   and builds them an executor bound to it — fully isolated per `(user,
   connector)`, so no token leaks between callers.
2. If that user hasn't connected the source, the tool returns **`AUTH_REQUIRED`**
   with a connect URL. The user opens it, completes the upstream login once,
   then retries — no token is ever pasted into the agent.
3. Expired access tokens are refreshed automatically using the stored refresh
   token + the app credentials.

Self-hosted note: in the standalone connector-runtime, a `per_user` source's
`secret_key` names the per-user vault slot the resolved token lands in (e.g.
`"access_token"`); the connect flow lives at `/oauth/start/{source_id}`. The
cloud uses the `{{ user_oauth:SOURCE_ID }}` placeholder shown above.

## Tool execution modes — when the upstream is actually hit

A connector's data is **not** permanently frozen at build time. Three modes:

1. **READ over a materialized snapshot (default).** On first call the source is
   fetched, flattened, and loaded into in-memory SQLite; the tool's SQL runs
   against it. The snapshot is cached with a **TTL (default 300s)** — the next
   call after the TTL expires re-fetches. This is why fresh upstream rows can
   appear "stale" for up to the TTL; it is a cache, not a build-time freeze.
2. **READ passthrough (live).** A READ tool that declares `rest_query_params`
   forwards those agent arguments as live query-string params and **fetches
   fresh on every call**, bypassing the snapshot cache. Use when the answer
   must vary per call (e.g. `?q=<arg>` search, `?resource_id=<arg>` lookups).
3. **WRITE / ACTION (live).** A `WRITE` or `ACTION` tool is backed by
   `api_mapping` (not SQL) and makes a fresh HTTP request per invocation,
   injecting the tool's parameters into the request:
   - `path_template` → URL path (`/issues/{number}`)
   - `query_params` → query string
   - `body_params` → JSON / form body
   The response is returned to the agent directly (not loaded into SQLite).

Note: auth headers always come from `source.auth` — a tool **parameter** never
becomes the auth header. "Each caller brings their own token" is expressed with
`scope: per_user`, not by adding a `token` parameter to a tool.
"""


_ERROR_CODES_MD = """# Elliot Error Codes

Every `ElliotError` raised by the platform uses a stable code. When an agent
encounters one of these, it has a deterministic recovery path. Codes are
intentionally coarse — fine-grained details live in the `details` field.

| Code | When raised | Recovery |
|------|-------------|----------|
| `VALIDATION_INVALID_PARAMS` | A tool was called with the wrong argument shape | Read the schema (`tools/list`) and resend with corrected args |
| `VALIDATION_MISSING_FIELD` | Required field omitted | Re-call with the missing field populated |
| `TOOL_NOT_FOUND` | Referenced tool id does not exist in the registry | List tools (`elliot_list_tools`); use a valid id |
| `SOURCE_UNREACHABLE` | A configured source did not respond | Check the env var holding the URL; verify the user has network access |
| `AUTH_FAILED` | Source rejected credentials | Confirm the env var name and that it's exported in the shell — do NOT ask the user for the secret value |
| `AUTH_REQUIRED` | A `per_user` source was called by a user who hasn't connected their account yet | Surface the connect URL(s) from `details.connect`; the user logs in once, then retry the tool. See `elliot://docs/authentication`. |
| `SCHEMA_NOT_FOUND` | Postgres/MySQL schema does not exist | Pick from `details.available` |
| `QUERY_TIMEOUT` | A DB query exceeded the per-query timeout | Tighten filters, add an index, or split the request |
| `INVALID_SKILL` | Skill definition failed validation | Read the message; each step needs `{alias, tool_id, params}` |
| `INTERNAL_ERROR` | Unexpected exception inside Elliot | Report to the user; the stack trace is in the server log |

If you see a code not in this table, treat it as `INTERNAL_ERROR` for recovery
purposes and surface the message verbatim to the user.
"""


_INSTALL_MD = """# Installing Elliot in Your Project

Elliot is an MCP server. Your agent connects to it over HTTP and gains access
to the tools you've built.

## Important: the server still needs to be running

Every install path below just wires up the *URL* — `http://localhost:3000/mcp/`.
None of them brings up the Elliot server itself. You also need ONE of:

- Run `make dev` in a clone of `EliBarak12/Elliot` (boots plugin + runtime + studio).
- Run `uvx --from elliot-mcp-plugin uvicorn elliot_mcp_plugin.main:app --port 3000`
  (once the package is published on PyPI).
- Point at a hosted Elliot endpoint (see "Remote" below) — not yet available.

If the URL is wired but the server isn't running, every Elliot tool call returns
a connection error. The recovery is always: start the server.

## 1. Marketplace install (Claude Code)

```
/plugin marketplace add EliBarak12/elliot
/plugin install elliot@elliot
```

This copies the Elliot plugin into `~/.claude/plugins/elliot/` — skills, the
plugin manifest, and the `.mcp.json` that points at `localhost:3000`. Claude
Code reads `.claude-plugin/marketplace.json` at the cloned repo root and the
plugin's own `.claude-plugin/plugin.json` to discover skills under `skills/`.

Works against the default branch of the repo — until `main` carries these
manifests, you need to install from a feature branch via the GitHub source
form.

## 2. Marketplace install (Codex)

```
codex plugin marketplace add EliBarak12/Elliot
```

Then open the plugin directory in Codex, pick the `elliot` marketplace, and
install the `elliot` plugin. Codex reads `.agents/plugins/marketplace.json` at
the cloned repo root and the plugin manifest at `.codex-plugin/plugin.json`,
which declares the skills under `skills/` and the Elliot MCP server.

## 3. Standalone install (no clone)

```
npx @elliot/connect
```

This detects every coding agent on your machine and writes the right MCP
config for each. Skills still travel through the MCP server itself via
`prompts/list`. NOT YET PUBLISHED to npm — the logic lives in
`packages/mcp-plugin/scripts/install.py`.

## 4. One-click IDE install (VS Code, Cursor, Windsurf)

These IDEs accept MCP-install deeplinks. Click the matching link from the
Elliot README — they pre-fill the config and prompt you to confirm:

- VS Code: `vscode:mcp/install?{"name":"elliot","type":"http","url":"http://localhost:3000/mcp/"}`
- Cursor:  `cursor:install-mcp?config={"name":"elliot","type":"http","url":"http://localhost:3000/mcp/"}`

## 5. Manual config (always works)

Add to your agent's MCP config:

```json
{
  "mcpServers": {
    "elliot": {
      "type": "http",
      "url": "http://localhost:3000/mcp/"
    }
  }
}
```

For Codex (TOML):
```toml
[mcp_servers.elliot]
url = "http://localhost:3000/mcp/"
```

## First connection

On first connection, call `prompts/get name=getting_started`. That single
prompt teaches you the canonical workflow and which other prompts to invoke
for each task.
"""


def _load_templates_dir() -> Path | None:
    """Locate `packages/core/src/elliot_core/templates/`."""
    try:
        # importlib.resources is the canonical way to find package data
        traversable = importlib.resources.files("elliot_core") / "templates"
        # Convert Traversable -> Path. Most setups give a concrete filesystem
        # path; if not (e.g. zipimport), bail out gracefully.
        path = Path(str(traversable))
        if path.is_dir():
            return path
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass

    # Fallback: walk up from this file to find the workspace
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "packages" / "core" / "src" / "elliot_core" / "templates"
        if candidate.is_dir():
            return candidate
    return None


def _slug_from_template_filename(filename: str) -> str:
    """`rest-api-key.connector.json` -> `rest-api-key`."""
    base = filename
    if base.endswith(".connector.json"):
        base = base[: -len(".connector.json")]
    return base


def register_resources(mcp: FastMCP) -> int:
    """Register reference docs and connector templates as MCP resources.

    Returns the count of resources registered.
    """
    count = 0

    def _add_text(uri: str, name: str, description: str, body: str) -> None:
        nonlocal count

        # FastMCP introspects the function signature and treats any param as a
        # URI template variable. Use a closure with zero positional args so the
        # URI is treated as a static (non-templated) resource.
        def make_reader(payload: str) -> Callable[[], str]:
            def _read() -> str:
                return payload

            return _read

        reader = make_reader(body)
        reader.__doc__ = description
        mcp.resource(uri, name=name, description=description, mime_type="text/markdown")(reader)
        count += 1

    _add_text(
        "elliot://docs/principles",
        "principles",
        "Elliot's five design principles for agent-ready tools.",
        _PRINCIPLES_MD,
    )
    _add_text(
        "elliot://docs/error-codes",
        "error-codes",
        "Stable ElliotError codes and their recovery paths.",
        _ERROR_CODES_MD,
    )
    _add_text(
        "elliot://docs/authentication",
        "authentication",
        "Auth model (shared vs per-user), secret placeholders, and when tools "
        "fetch upstream (snapshot TTL, live passthrough, WRITE/ACTION).",
        _AUTH_MD,
    )
    _add_text(
        "elliot://docs/install",
        "install",
        "How to install Elliot into Claude Code, Codex, Cursor, VS Code, or Windsurf.",
        _INSTALL_MD,
    )

    templates_dir = _load_templates_dir()
    if templates_dir is None:
        log.warning("resources.templates_dir.not_found")
    else:
        for tpl in sorted(templates_dir.glob("*.connector.json")):
            slug = _slug_from_template_filename(tpl.name)
            body = tpl.read_text(encoding="utf-8")
            uri = f"elliot://templates/{slug}"

            def make_template_reader(payload: str) -> Callable[[], str]:
                def _read() -> str:
                    return payload

                return _read

            reader = make_template_reader(body)
            description = f"Starter connector template: {slug}"
            reader.__doc__ = description
            mcp.resource(
                uri,
                name=f"template-{slug}",
                description=description,
                mime_type="application/json",
            )(reader)
            count += 1
            log.info("resources.template.registered", slug=slug)

    log.info("resources.registered", count=count)
    return count
