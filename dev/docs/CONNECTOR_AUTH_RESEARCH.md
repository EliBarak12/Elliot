# Elliot — Per-User Connector Authentication: Research & Implementation Plan

How MCP authentication works on the wire today, where Elliot stands, and a
concrete plan to let a connector run **in the scope of the end user** — each
user goes through their own auth (OAuth flow or their own API key), Elliot
holds a per-user token, and every tool call hits the upstream API as that user.
Includes the distribution case: an author builds one connector and ships it to
many users who each authenticate separately.

> Headline: MCP auth is really **two separate boundaries** — (1) the agent
> authenticating *to* the MCP server, and (2) the MCP server authenticating *to
> the upstream API on behalf of the user*. Elliot already has a weak version of
> (1) (a single service API key) and a **single-tenant** version of (2) (one
> global set of `ELLIOT_SECRET_*` env vars). Per-user auth is almost entirely
> about boundary (2): making the upstream credential **request-scoped and keyed
> by user** instead of process-global. The single biggest code change is moving
> secrets out of `ToolExecutor.__init__` and into the per-call execution path.

---

## Part 1 — How MCP authentication works (the spec, technically)

### 1.1 The two boundaries (this is the whole mental model)

```
                  boundary (1)                    boundary (2)
   ┌────────┐   agent → MCP server   ┌──────────┐  MCP server → upstream  ┌────────────┐
   │ Agent /│ ─────────────────────► │  Elliot   │ ──────────────────────► │ Upstream   │
   │ client │   OAuth 2.1 / API key  │ MCP server│  user's token / API key │ API or DB  │
   └────────┘   (who is calling?)    └──────────┘  (act as which user?)    └────────────┘
        client                    resource server +              the actual product
                                   OAuth client to upstream       being made agentic
```

- **Boundary (1) — agent ↔ MCP server.** The current MCP spec (2025-06 →
  draft 2026) says a protected MCP server is an **OAuth 2.1 resource server**
  and the MCP client is an **OAuth 2.1 client**. This answers "*is this caller
  allowed to use this server, and who are they?*"
- **Boundary (2) — MCP server ↔ upstream.** Separate and **out of scope of the
  MCP spec**. This is "*now that I know who the user is, how do I call GitHub /
  Stripe / their Postgres as them?*" For Elliot this is the important one,
  because a connector's whole job is to call an upstream product.

A lot of confusion online comes from collapsing these two. Keep them separate.

### 1.2 Boundary (1): the OAuth 2.1 discovery + authorization flow

The spec composes several RFCs. Sequence for a remote (HTTP) MCP server:

1. **Unauthenticated probe.** Client calls the MCP server with no token →
   server returns **`401 Unauthorized`** with a **`WWW-Authenticate`** header
   pointing at the server's resource-metadata URL.
2. **Protected Resource Metadata — RFC 9728 (MUST).** Client fetches
   `/.well-known/oauth-protected-resource`. The document MUST contain an
   `authorization_servers` field listing at least one authorization server
   (AS). This is how the client *discovers* where to authenticate — the MCP
   server itself need not be the AS.
3. **Authorization Server Metadata — RFC 8414.** Client fetches the AS's
   `/.well-known/oauth-authorization-server` to learn the `authorization_endpoint`,
   `token_endpoint`, `registration_endpoint`, supported scopes, etc.
4. **Dynamic Client Registration — RFC 7591 (SHOULD).** If the client has no
   pre-registered `client_id`, it registers on the fly at the
   `registration_endpoint`. This is what lets *any* MCP client connect to *any*
   MCP server without a human pre-provisioning credentials.
5. **Authorization Code + PKCE (MUST, OAuth 2.1).** Client opens the user's
   browser to the `authorization_endpoint` with `code_challenge` (PKCE) and a
   **`resource` parameter (Resource Indicators, RFC 8707, MUST)** that names the
   MCP server as the intended audience. User logs in / consents, AS redirects
   back with a `code`.
6. **Token exchange.** Client posts `code` + `code_verifier` to the
   `token_endpoint`, receives an **access token** (and usually a refresh token).
7. **Authenticated calls.** Client sends `Authorization: Bearer <token>` on
   every MCP request. The MCP server **MUST validate** the token — signature,
   expiry, issuer, and crucially the **audience** (was this token actually
   minted for *this* server?).

### 1.3 The cardinal anti-pattern: token passthrough / confused deputy

The spec explicitly says the MCP server **MUST NOT** take the token it received
at boundary (1) and replay it to the upstream API at boundary (2). Reasons:

- **Audience confusion.** A token minted for the MCP server is not valid for,
  say, the GitHub API. Accepting tokens not issued *for* this server is the
  "token passthrough" anti-pattern.
- **Confused deputy.** If the server blindly forwards a caller-supplied token to
  a downstream it has more privilege on, a malicious caller can borrow the
  server's authority.

So boundary (2) needs its **own** credential, derived per user. That is exactly
the gap Elliot must fill.

### 1.4 Boundary (2): how the server gets an upstream credential *as the user*

Three patterns in the wild, in increasing sophistication:

| Pattern | How it works | When Elliot uses it |
|---|---|---|
| **Per-user API key / PAT** | The end user pastes their own key for the upstream (e.g. a Stripe restricted key). Server stores it keyed by user and injects it on upstream calls. | Upstream has no OAuth — only API keys. The common case. |
| **Per-user OAuth (server as OAuth client to upstream)** | Server runs a *second* OAuth dance, this time as a **client to the upstream provider** (Google, GitHub, Slack…). It stores the user's upstream access+refresh tokens and refreshes them. | Upstream supports OAuth (most SaaS). The gold standard for "act as the user". |
| **Token Exchange — RFC 8693** | Server presents the boundary-(1) token to a Security Token Service and gets back a *new* token with the right audience/scope for the upstream. Needs an identity provider that supports it. | Enterprise / federated deployments; later phase. |

Credentials at boundary (2) are typically held in a **token vault** keyed by
`(user_id, connector, source)` — "store the user's credential once, transparently
inject it into upstream requests." For OAuth upstreams the vault also stores the
refresh token and the server refreshes access tokens lazily on expiry.

### 1.5 Collecting the credential at runtime

Two UX routes for getting the user's upstream credential:

- **Out-of-band / Studio connect button.** A web page where the user clicks
  "Connect GitHub", does the OAuth dance, and a callback stores their tokens.
  Best UX for OAuth.
- **MCP elicitation.** The newer MCP feature lets a server, mid-session, ask the
  client to prompt the user for input (e.g. "paste your API key" or "open this
  URL to authorize"). Good for API-key upstreams and for clients without a web UI.

---

## Part 2 — Where Elliot stands today

From the codebase (`packages/core`, `packages/mcp-plugin`, `packages/connector-runtime`):

| Aspect | Today | Implication for per-user auth |
|---|---|---|
| Auth types in schema | `api_key`, `bearer`, `basic`, `oauth2` — `AuthConfig` in `core/.../types/source.py` | `oauth2` is **schema-only**; no flow implemented. |
| Secret resolution | `{{ env:VAR }}` → `resolve_secrets()` / `_resolve_secret()` in `core/.../secrets.py` and `sources/api_fetcher.py` | Resolves from process env only — one value per var, globally. |
| REST credential injection | `_build_auth_headers()` / `_build_auth_query_params()` in `api_fetcher.py` and `connector-runtime/.../executor.py` | Header/param built from a `secrets` dict — *swappable per user if the dict is per-request.* |
| DB credential | `_resolve_dsn()` in `core/.../sources/db_connector.py` — DSN from `{{ env:DATABASE_URL }}` | One DSN for everyone; no per-user role. |
| **Scope of secrets** | `ToolExecutor.__init__(config, secrets)` stores `self._secrets`; every `execute()` reuses it | **The core blocker.** Secrets are process-global, not per-call. |
| Service auth (boundary 1) | `ApiKeyMiddleware` checks one global `ELLIOT_API_KEY` (`core/.../auth_middleware.py`) | Authenticates *that a caller is allowed*, but carries **no user identity**. |
| Identity context | `AgentIdentity` + `AgentIdentityMiddleware` (contextvars) | Captures *which AI tool/model* called — **not which end user**. Reusable plumbing, wrong subject. |
| Multi-tenancy | None | No `user_id` anywhere; no per-user store; no token vault. |

**Net:** Elliot is single-tenant. It already injects credentials per source and
already has request-scoped contextvar plumbing — but the credential is global and
the identity it tracks is the agent, not the user.

---

## Part 3 — What "per-user auth" should mean in Elliot

Concretely, the target behavior:

1. A connector author marks a source's auth as **`per_user`** (vs `shared`).
2. When an end user first uses such a connector, Elliot drives them through the
   right onboarding: an OAuth dance (oauth2) or a prompt for their own key
   (api_key/bearer/basic) or their own DB credential.
3. Elliot stores that credential in a **per-user vault**, keyed by
   `(user_id, connector_slug, source_id)`.
4. On every tool call, Elliot resolves the **calling user's** credential and
   injects it at boundary (2), so the upstream sees the request as that user —
   results are naturally scoped to what that user can see.
5. Author-level secrets (e.g. the OAuth **client secret** of the upstream app)
   stay global; only the **user token** is per-user.

Two layers must be built:

- **Identity layer (boundary 1):** establish a stable `user_id` for the caller.
- **Credential layer (boundary 2):** per-user vault + per-request resolution +
  the OAuth/API-key acquisition flows.

---

## Part 4 — Design

### 4.1 Connector schema changes (`core/.../types/source.py`)

Extend `AuthConfig` so an author can declare *who owns the credential* and, for
OAuth, *how to run the dance*:

```python
class OAuth2Config(BaseModel):
    authorization_url: str           # upstream AS authorize endpoint
    token_url: str                   # upstream AS token endpoint
    scopes: list[str] = []
    client_id_secret: str            # {{ env:GITHUB_CLIENT_ID }}  (author-level)
    client_secret_secret: str        # {{ env:GITHUB_CLIENT_SECRET }} (author-level)
    # PKCE on by default; refresh handled by Elliot

class AuthConfig(BaseModel):
    type: Literal["api_key", "bearer", "basic", "oauth2"]
    scope: Literal["shared", "per_user"] = "shared"   # NEW
    header_name: str | None = None
    query_param: str | None = None
    secret_key: str | None = None        # used when scope="shared" (today's behavior)
    oauth2: OAuth2Config | None = None    # required when type="oauth2"
```

`scope="shared"` keeps **100% of today's behavior** (env-var secret, single
tenant) — fully backward compatible. `scope="per_user"` activates the new path.

### 4.2 The core change: request-scoped credential resolution

Today `ToolExecutor` binds `self._secrets` at init. Introduce a **credential
resolver** that is consulted **per execute()**, given the calling user:

```python
class CredentialResolver(Protocol):
    async def resolve(self, user_id: str | None, source: SourceConfig) -> dict[str, str]:
        ...
```

- `execute(name, arguments)` → `execute(name, arguments, *, user_id)`.
- For `scope="shared"` sources, the resolver returns the existing env-derived
  secret (no behavior change, `user_id` ignored).
- For `scope="per_user"` sources, the resolver looks up the user's vault entry,
  refreshing an OAuth token if expired, and returns the live credential.

`_build_auth_headers` / `_build_auth_query_params` / `_resolve_dsn` already take
a `secrets`-shaped dict, so they need almost no change — they just receive the
**per-user** dict the resolver produced.

### 4.3 Establishing `user_id` (boundary 1)

Reuse the `AgentIdentityMiddleware` pattern (`core/.../http_middleware.py`) to
add a **user** contextvar populated from one of:

- the validated boundary-(1) OAuth token's `sub` claim (preferred for remote
  HTTP/SSE deployments), or
- a signed `X-Elliot-User` header issued by the deployer's gateway, or
- for local stdio/dev, a fixed `local` user.

Store it as `get_current_user_id()` so the executor can read it without threading
it through every signature.

### 4.4 Per-user credential vault

A new store keyed by `(user_id, connector_slug, source_id)`:

```python
@dataclass
class UserCredential:
    user_id: str
    connector_slug: str
    source_id: str
    kind: Literal["api_key", "oauth2"]
    secret: str                    # api key / bearer / basic, OR oauth access token
    refresh_token: str | None = None
    expires_at: float | None = None
    scopes: list[str] = field(default_factory=list)
```

- **Storage:** encrypted-at-rest. Phase 1 can be a SQLite table (a
  `SQLiteEngine` already exists in the runtime) with values encrypted via a
  deployment KMS key; later, pluggable backends (HashiCorp Vault, cloud secret
  managers).
- **Never logged** — honor the CLAUDE.md "never log secret values" rule; log
  only `secrets resolved` boundary events with the user id and source, no value.

### 4.5 Per-mode behavior

**REST — `api_key` / `bearer` / `basic`, `scope="per_user"`**
- Onboarding: elicitation or Studio prompt → user pastes *their* key → vault.
- Per call: resolver returns `{secret_key_alias: <user key>}`;
  `_build_auth_headers` injects it exactly as today. No change to the request path.

**REST — `oauth2`, `scope="per_user"`** (the "act as the user" gold path)
- Onboarding: Studio "Connect" button (or elicited URL) → Elliot runs Auth Code
  + PKCE against `oauth2.authorization_url`/`token_url` using the **author-level**
  `client_id`/`client_secret`, with a callback endpoint
  (`/oauth/callback/<connector>/<source>`) that stores access+refresh tokens in
  the vault keyed by the calling user.
- Per call: resolver checks `expires_at`; if stale, refreshes via `token_url`
  and updates the vault; returns `{... : "Bearer <access token>"}`.
- This is boundary (2) OAuth — Elliot is an **OAuth client to the upstream**,
  *not* passing through the boundary-(1) token (avoids the confused-deputy
  anti-pattern in §1.3).

**DB — `postgres` / `mysql`, `scope="per_user"`**
- Two sub-strategies:
  1. **Per-user DSN/role:** vault holds the user's own DB credentials; resolver
     builds their DSN. Upstream RLS/grants enforce scope. Cleanest isolation.
  2. **Shared connection + injected identity:** keep one pooled connection but
     `SET app.current_user = :user_id` (Postgres `SET LOCAL` / session GUC) so
     row-level-security policies filter results. Lighter on connections; relies
     on the target DB having RLS configured.
- Honor the existing read-only enforcement in `db_connector.py`. Pooling must be
  **per-DSN** so users don't share a privileged connection.

### 4.6 What stays global vs per-user

| Credential | Owner | Where |
|---|---|---|
| Upstream OAuth **client_id / client_secret** | Connector author / deployer | env (`{{ env:... }}`), global |
| Upstream **user access/refresh token** | End user | per-user vault |
| User's own **API key / PAT** | End user | per-user vault |
| Per-user **DB credential** | End user | per-user vault |
| Elliot **service API key** (boundary 1) | Deployer | env, global (today's `ELLIOT_API_KEY`) |

---

## Part 5 — Distribution scenario

The author builds a connector once and ships it; many users run it, each
authenticating as themselves.

**What the author ships (no secrets):**
- The `connector.json` with sources marked `scope="per_user"` and, for OAuth,
  the `oauth2` block describing the upstream's `authorization_url`, `token_url`,
  and `scopes` — but referencing client credentials only as `{{ env:... }}`
  placeholders, never literal values. (Elliot already bundles connectors as
  plugins — see the `feat(plugin)` commits — so this rides existing packaging.)

**What the deployer supplies once (author/app-level):**
- The upstream OAuth **app** registration: `client_id` + `client_secret` set as
  env vars on their Elliot instance. (For pure API-key upstreams there may be
  nothing app-level — each user just brings their own key.)

**What each end user does (per-user):**
- First use → Elliot detects no vault entry for `(user_id, connector, source)` →
  drives the OAuth "Connect" flow or elicits their API key → stores their token.
- Thereafter every tool call runs in **their** scope automatically.

**Validation/safety for distribution:**
- The connector linter should **reject literal secrets** in a distributable
  connector and require `per_user` sources to declare a complete `oauth2` block
  or an explicit api-key prompt.
- Surface a "this connector will ask each user to connect their <Provider>
  account" notice at install time so consumers understand the auth requirement.
- A marketplace listing only needs the connector definition + the upstream app's
  client id; secrets and user tokens never travel with the artifact.

---

## Part 6 — Phased roadmap (mapped to files)

**Phase 0 — Schema + backward-compat (no behavior change)**
- Add `scope` + `OAuth2Config` to `AuthConfig` in
  `packages/core/src/elliot_core/types/source.py`; default `shared`.
- Linter: forbid literal secrets; require `oauth2` block when
  `type="oauth2"`. Tests for both.

**Phase 1 — Request-scoped credentials + per-user API keys (REST)**
- Introduce `CredentialResolver`; thread `user_id` into
  `ToolExecutor.execute()` (`connector-runtime/.../executor.py`) and the
  MCP `call_tool` handler (`mcp-plugin/.../server.py`).
- Add `user_id` contextvar + middleware alongside `AgentIdentityMiddleware`.
- Add the SQLite-backed encrypted vault; api-key onboarding via elicitation.
- Keep `shared` path identical (resolver returns env secret).

**Phase 2 — Per-user OAuth (REST oauth2)**
- OAuth client: Auth Code + PKCE against upstream, callback endpoint, refresh.
- Studio "Connect <Provider>" UI + connection status per source.

**Phase 3 — Per-user DB**
- Per-user DSN/role resolution and/or RLS session-variable injection in
  `core/.../sources/db_connector.py`; per-DSN pooling.

**Phase 4 — Federation / enterprise**
- RFC 8693 token exchange and pluggable vault backends (Vault, cloud KMS).

---

## References

- [Authorization — Model Context Protocol (spec)](https://modelcontextprotocol.io/specification/draft/basic/authorization)
- [Understanding Authorization in MCP (tutorial)](https://modelcontextprotocol.io/docs/tutorials/security/authorization)
- [Is that allowed? Authentication and authorization in MCP — Stack Overflow](https://stackoverflow.blog/2026/01/21/is-that-allowed-authentication-and-authorization-in-model-context-protocol/)
- [The New MCP Authorization Specification — OAuth 2.1 & Resource Indicators](https://dasroot.net/posts/2026/04/mcp-authorization-specification-oauth-2-1-resource-indicators/)
- [MCP, OAuth 2.1, PKCE, and the Future of AI Authorization — Aembit](https://aembit.io/blog/mcp-oauth-2-1-pkce-and-the-future-of-ai-authorization/)
- [MCP Authorization Patterns for Upstream API Calls — Solo.io](https://www.solo.io/blog/mcp-authorization-patterns-for-upstream-api-calls)
- [MCP Authorization Patterns for Upstream API Calls — ceposta](https://blog.christianposta.com/mcp-authorization-patterns-upstream-api-calls/)
- [Beyond API Keys: Token Exchange, Identity Federation & MCP Servers — Stacklok](https://dev.to/stacklok/beyond-api-keys-token-exchange-identity-federation-mcp-servers-5dm8)
- [Guidance on per-user credentials for a remote MCP proxy — MCP Discussion #561](https://github.com/orgs/modelcontextprotocol/discussions/561)
- [Set up MCP server authentication — Microsoft Foundry](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/mcp-authentication?view=foundry)
- [Authorization — Cloudflare Agents docs](https://developers.cloudflare.com/agents/model-context-protocol/authorization/)
- [MCP Authentication: OAuth, API Keys, and Token Management — Maxim](https://www.getmaxim.ai/articles/mcp-authentication-explained-oauth-api-keys-and-token-management/)
