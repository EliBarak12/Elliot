from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class OAuth2Config(BaseModel):
    """Per-user OAuth 2.1 (authorization-code + PKCE) settings for a source.

    Describes the *upstream* provider's endpoints and the connector author's
    OAuth app credentials. The author's client id/secret are app-level and use
    ``{{ env:VAR }}`` placeholders; the per-user access/refresh tokens are
    never part of the connector file — Elliot mints and stores them per end
    user at connect time.
    """

    model_config = ConfigDict(extra="forbid")

    authorization_url: str
    token_url: str
    scopes: list[str] = []
    client_id_secret: str  # {{ env:VAR }} — author/app-level
    client_secret_secret: str  # {{ env:VAR }} — author/app-level
    # Where the upstream sends the user identity, if the connector wants it
    # surfaced; optional and unused by the token-injection path.
    userinfo_url: str | None = None


class AuthConfig(BaseModel):
    """Authentication for a source.

    The credential always lives in ``secret_key`` (a ``{{ env:VAR }}`` template
    for shared auth, or a vault slot name for per-user auth). Expected
    ``secret_key`` content per type:

      * ``api_key`` — the key value; ``header_name`` or ``query_param`` names where it goes.
      * ``bearer``  — the token (sent as ``Authorization: Bearer <secret_key>``).
      * ``basic``   — ``"username:password"`` (base64-encoded into the Basic header).
      * ``oauth2``  — handled per-user; see ``oauth2``.

    The MCP ``elliot_discover_source`` tool also accepts the ergonomic aliases
    ``token`` (bearer) and ``username`` + ``password`` (basic) and normalizes
    them into ``secret_key`` before this model is constructed.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["api_key", "bearer", "basic", "oauth2"]
    # "shared": one credential resolved from {{ env:VAR }}, same for every
    # caller (the original behaviour). "per_user": each end user supplies or
    # authorises their own credential, which Elliot stores in a per-user vault
    # keyed by (user_id, connector, source) and injects per request.
    scope: Literal["shared", "per_user"] = "shared"
    header_name: str | None = None
    query_param: str | None = None
    # For shared auth: a {{ env:VAR }} template / env name. For per_user auth:
    # the vault slot name under which the resolved per-user token is injected.
    secret_key: str
    # Required when type == "oauth2"; describes the upstream OAuth provider.
    oauth2: OAuth2Config | None = None


class PaginationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["cursor", "offset", "page", "link_header", "none"] = "none"
    page_size: int = 100
    max_pages: int = 10
    cursor_field: str | None = None  # response field that holds the next cursor
    next_url_field: str | None = None  # response field that holds the next page URL


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    type: Literal["rest", "postgres", "mysql", "file"]

    # REST
    url: str | None = None
    method: Literal["GET", "POST"] = "GET"
    auth: AuthConfig | None = None
    pagination: PaginationConfig = PaginationConfig()
    data_path: str | None = None  # jmespath to extract list from response
    timeout_ms: int = 30_000

    # DB (postgres / mysql)
    table: str | None = None
    query: str | None = None

    # File
    path: str | None = None
    format: Literal["csv", "json", "jsonl"] | None = None
    encoding: str = "utf-8"
    delimiter: str = ","

    # Runtime tracking (populated after a fetch)
    table_name: str | None = None
    row_count: int | None = None
    config_snapshot: dict[str, Any] | None = None


class FetchResult(BaseModel):
    rows: list[dict[str, Any]]
    fetched_at: str
    page_count: int = 1
    warnings: list[str] = []
    # Populated by passthrough fetcher so the agent knows how to get the next page.
    # Keys depend on pagination strategy: next_cursor, next_url, total, has_more, etc.
    pagination_meta: dict[str, Any] = {}
