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

from elliot_core.mcp_compat import FastMCP

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
connector author's (app-level) OAuth client credentials.

> **This is a TEMPLATE, not a connector to build.** Replace every value —
> `id`, `url`, the OAuth endpoints, scopes, and the `{{ env:... }}` names — with
> your actual provider's (GitHub, Slack, Gmail, …). Never ship the placeholder
> source as-is; it is only here to show the shape.

```json
{
  "id": "your_source",
  "type": "rest",
  "url": "https://api.your-provider.com/me",
  "auth": {
    "type": "oauth2",
    "scope": "per_user",
    "secret_key": "{{ user_oauth:your_source }}",
    "oauth2": {
      "authorization_url": "https://your-provider.com/login/oauth/authorize",
      "token_url": "https://your-provider.com/login/oauth/token",
      "scopes": ["..."],
      "client_id_secret": "{{ env:YOUR_PROVIDER_CLIENT_ID }}",
      "client_secret_secret": "{{ env:YOUR_PROVIDER_CLIENT_SECRET }}"
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

Build time (discovering an `oauth2` source): to learn the schema, discover needs
a token to fetch sample rows — but **never ask the user to paste one**. Call
`elliot_connect_source(source_type, config, name)` first; it returns an
`authorize_url`. The builder opens it, logs in to the upstream on the provider's
own page, and Elliot captures the token on a loopback callback. Then
`elliot_discover_source` (same args) uses that token to fetch.

Before that login can work, the OAuth **app** credentials must exist. Tell the
user up front (don't wait for the error): register an OAuth app in the
provider's developer settings, allow a `http://127.0.0.1` loopback redirect URL,
and export the **Client ID** + **Client Secret** as the env vars named in
`client_id_secret` / `client_secret_secret`. These are app-level, one-time
credentials — the very same ones their end users' runtime login uses — not a
personal token. If they're missing, `elliot_connect_source` returns
`AUTH_REQUIRED` explaining exactly this. The builder token from the login is used
for discovery only and is never written into the connector file — end users still
authenticate themselves at runtime.

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
encounters one of these, it has a deterministic recovery path. The error you
receive over MCP is the string `[CODE] message`, and the **message always
carries the specifics you need to recover** — the available table/column names,
the connect URL(s), the valid ids. (Errors also have a structured `details`
field, but that is for the server-side audit log and is not sent over MCP, so
recover from the message text, not from a `details.*` field.)

Calling a **published connector's** tools (the tools you build) can return:

| Code | When raised | Recovery |
|------|-------------|----------|
| `MISSING_PARAM` | A required parameter was omitted | The message names the parameter and its type, allowed `enum` values, numeric bounds, and description — supply a matching value and re-call |
| `INVALID_PARAM_TYPE` | A value could not be coerced to the parameter's declared type | The message names the parameter and the expected type — resend that one argument as the correct type |
| `INVALID_PARAM_VALUE` | A value broke the parameter's `enum` or numeric `minimum`/`maximum` | The message states the allowed values or the bound — pick a valid one and re-call |
| `UNKNOWN_PARAM` | A parameter the tool does not accept was passed | The message lists the accepted parameter names — drop the unknown key |
| `CONFIRMATION_REQUIRED` | A destructive (danger-zone) tool was called without `confirm=true` | Confirm the action with the user, then re-call the same tool with `confirm=true` |
| `AUTH_REQUIRED` | A `per_user` source was called by a user who hasn't connected their account yet | Open the connect URL(s) included in the error message; the user logs in once, then retry the tool. See `elliot://docs/authentication`. |
| `AUTH_FAILED` | Source rejected credentials | Confirm the env var name and that it's exported in the shell — do NOT ask the user for the secret value |
| `UPSTREAM_FETCH_FAILED` | A REST/DB source did not respond or returned an error status | The message carries the status/reason — check the source URL and its env var, and the user's network; retry if it looks transient |
| `TABLE_NOT_FOUND` | A tool's SQL references a table the connector did not materialize | Read the available table names from the message; fix the tool's `source_ids`/SQL |
| `SKILL_TEMPLATE_UNRESOLVED` | A skill step's `{{ … }}` binding did not resolve | The message shows the bad reference and the valid syntax: `{{ skill.input.<name> }}` for an input, `{{ steps.<alias>.<field> }}` for an earlier step's field |
| `TOOL_NOT_FOUND` | Referenced tool id does not exist in the registry | List tools (`tools/list`); use a valid id |
| `INVALID_SKILL` | Skill definition failed validation | Read the message; each step needs `{alias, tool_id, params}`, and a skill needs at least one step or non-empty instructions |
| `INTERNAL_ERROR` | Unexpected exception inside Elliot | Report to the user; the stack trace is in the server log |

Calling the **builder** tools (`elliot_*`) with a bad argument shape returns a
`VALIDATION_*` code instead — `VALIDATION_MISSING_FIELD` (a required field was
omitted) or `VALIDATION_INVALID_PARAMS` (wrong type/shape). Recover the same way:
read the tool schema (`tools/list`) and resend with corrected args.

If you see a code not in this table, treat it as `INTERNAL_ERROR` for recovery
purposes and surface the message verbatim to the user.

## Not every next-step signal is an error

A **successful** READ result can still tell you what to do next. It may carry:

- `truncated: true` with a `truncation_note` — the set was capped; narrow the
  request (tighten a filter or pass a smaller limit) and call again for the rest.
- `empty: true` with an `empty_note` — no rows matched; relax or drop a filter
  you supplied, or accept the result as genuinely empty rather than retrying.

Read those notes the same way you read an error message: the note states the
next step. Every result also carries `estimated_tokens`, the context-window cost
of what you just received — use it to decide whether to narrow the next call.
"""


_CUSTOM_APPS_MD = """# Custom MCP Apps Views — Author Your Own Tool UI

Every Elliot tool can ship an interactive view (MCP Apps ext, 2026-01-26).
The built-in presets (`table`, `detail`, `metric`, `chart`, `markdown`) cover
most tools; when a tool needs a bespoke UI, set the tool's ui config to a
fully custom document:

```json
{"ui": {"enabled": true, "preset": "custom", "custom_html": "<!doctype html>…"}}
```

Save it via `elliot_update_tool(tool_id, patch={"ui": …})` and check the
result with `elliot_preview_tool_ui(tool_id)`. Rules:

- The document is served VERBATIM at `ui://<slug>/<tool_id>` — Elliot injects
  nothing (no branding, no config), you control everything.
- Budget: 256 KiB, self-contained (hosts sandbox the iframe; the default CSP
  allows no external requests — declare any API origins you call in
  `ui.csp_connect_domains`, and lint enforces this).
- Speak the MCP Apps postMessage protocol yourself (skeleton below): call
  `ui/initialize`, announce `ui/notifications/initialized`, then render on
  `ui/notifications/tool-result`. Use `ui/update-model-context` to tell the
  model what the user did — that is what makes a view agentic rather than
  decorative.
- Follow the host theme: style with the host CSS variables
  (`--color-background-primary`, `--color-text-primary`, `--color-border-primary`,
  `--font-sans`, …) and give every one a fallback for hosts that inject none.

## Working skeleton (copy into `custom_html`, then make it yours)

```html
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  :root { color-scheme: light dark;
    --bg: #ffffff; --fg: #16181d; --border: #e4e4e7; --accent: #c02434; }
  :root[data-theme="dark"] { --bg: #17181c; --fg: #ededef; --border: #2e3035; }
  body { margin: 0; padding: 14px;
    font-family: var(--font-sans, ui-sans-serif, system-ui, sans-serif);
    background: var(--color-background-primary, var(--bg));
    color: var(--color-text-primary, var(--fg)); }
  .card { border: 1px solid var(--color-border-primary, var(--border));
    border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; cursor: pointer; }
  .card:hover { border-color: var(--color-ring-primary, var(--accent)); }
  .k { opacity: .65; font-size: 12px; margin-right: 6px; }
</style>
</head>
<body>
<div id="root">Waiting for the tool result…</div>
<script>
(() => {
  let nextId = 0;
  const pending = new Map();
  const send = (msg) => parent.postMessage(msg, "*");
  const request = (method, params) => new Promise((resolve) => {
    const id = ++nextId;
    pending.set(id, resolve);
    send({ jsonrpc: "2.0", id, method, params });
  });

  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (!msg || msg.jsonrpc !== "2.0") return;
    if (msg.id !== undefined && pending.has(msg.id)) {
      pending.get(msg.id)(msg.result); pending.delete(msg.id); return;
    }
    if (msg.method === "ui/notifications/tool-result") render(msg.params);
  });

  function render(params) {
    const rows = (params.structuredContent && params.structuredContent.rows) || [];
    const root = document.getElementById("root");
    root.innerHTML = "";
    rows.forEach((row) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = Object.entries(row)
        .map(([k, v]) => `<span class="k">${k}</span>${String(v)}`)
        .join("<br>");
      card.onclick = () => request("ui/update-model-context", {
        content: [{ type: "text", text: "The user selected: " + JSON.stringify(row) }],
        structuredContent: { selected: row },
      });
      root.appendChild(card);
    });
    send({ jsonrpc: "2.0", method: "ui/notifications/size-changed",
           params: { height: document.documentElement.scrollHeight } });
  }

  request("ui/initialize", {
    protocolVersion: "2026-01-26",
    appInfo: { name: "my-custom-view", version: "1.0.0" },
    appCapabilities: {},
  }).then((result) => {
    const theme = result && result.hostContext && result.hostContext.theme;
    if (theme) document.documentElement.dataset.theme = theme;
    send({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
  });
})();
</script>
</body>
</html>
```
"""

_INSTALL_MD = """# Installing Elliot in Your Project

Elliot is an MCP server. Your agent connects to it over HTTP and gains access
to the tools you've built.

## The hosted endpoint

Every install path below wires up the *URL* — `https://api.elliot-cloud.com/b/mcp`,
the hosted Elliot Cloud builder. No local server is required: your agent
connects straight to Elliot Cloud and gets the same build/lint/eval/publish
tools and skills you'd run locally.

The endpoint is OAuth-protected. The config carries only the URL — on the first
tool call your agent opens a browser tab to authorize Elliot Cloud (no API key
to paste). After that the agent stays connected.

Prefer to run Elliot yourself? Boot the stack locally and point your agent at
your own URL instead of the hosted one:

- Run `make dev` in a clone of `EliBarak12/Elliot` (boots plugin + runtime +
  studio on `http://localhost:3000`), then `elliot connect` to wire every
  detected agent at the local URL.
- Run `uvx --from elliot-mcp-plugin uvicorn elliot_mcp_plugin.main:app --port 3000`
  (once the package is published on PyPI).

If the URL is wired but the endpoint is unreachable, every Elliot tool call
returns a connection error. The recovery is always: confirm the endpoint is up
and that you've authorized Elliot Cloud (or switch to a local URL).

## 1. Marketplace install (Claude Code)

```
/plugin marketplace add EliBarak12/elliot
/plugin install elliot@elliot
```

This copies the Elliot plugin into `~/.claude/plugins/elliot/` — skills, the
plugin manifest, and the `.mcp.json` that points at `api.elliot-cloud.com`. Claude
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

- VS Code: `vscode:mcp/install?{"name":"elliot","type":"http","url":"https://api.elliot-cloud.com/b/mcp"}`
- Cursor:  `cursor:install-mcp?config={"name":"elliot","type":"http","url":"https://api.elliot-cloud.com/b/mcp"}`

## 5. Manual config (always works)

Add to your agent's MCP config:

```json
{
  "mcpServers": {
    "elliot": {
      "type": "http",
      "url": "https://api.elliot-cloud.com/b/mcp"
    }
  }
}
```

For Codex (TOML):
```toml
[mcp_servers.elliot]
url = "https://api.elliot-cloud.com/b/mcp"
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
    _add_text(
        "elliot://docs/custom-apps",
        "custom-apps",
        "How to author a fully custom MCP Apps view for a tool (preset "
        "'custom'): the postMessage contract, CSP and size rules, and a "
        "complete working HTML skeleton to copy into ui.custom_html.",
        _CUSTOM_APPS_MD,
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
