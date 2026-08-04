from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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

    strategy: Literal["cursor", "offset", "page", "link_header", "odata", "none"] = "none"
    page_size: int = 100
    max_pages: int = 10
    cursor_field: str | None = None  # response field that holds the next cursor
    # Response field that holds the next-page URL. For ``odata`` this defaults to
    # the standard ``@odata.nextLink`` when left unset.
    next_url_field: str | None = None


class ManagedColumn(BaseModel):
    """One declared column of a managed ("elliot") source.

    Managed sources have no upstream to sample a schema from — the author
    declares the columns and Elliot provisions the table. ``type`` uses the
    same vocabulary as tool parameters so a WRITE tool's params map 1:1 onto
    columns.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["string", "integer", "number", "boolean", "date"] = "string"
    required: bool = False
    description: str = ""


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    type: Literal["rest", "postgres", "mysql", "file", "elliot"]

    # REST
    url: str | None = None
    method: Literal["GET", "POST", "PUT", "PATCH"] = "GET"
    auth: AuthConfig | None = None
    pagination: PaginationConfig = PaginationConfig()
    data_path: str | None = None  # jmespath to extract list from response
    timeout_ms: int = 30_000
    # Static request headers sent on every call to this source, ON TOP of the
    # single ``auth`` scheme above. This is what lets a source carry MORE than
    # one credential at once (e.g. a Bearer token via ``auth`` plus a custom
    # ``ecomtoken`` header and a session ``cookie`` here) and any non-secret
    # framing the upstream demands (``locale``, ``content-type``). Each value
    # may be a ``{{ env:VAR }}`` template so additional credentials never live
    # in the connector file. A header named here always loses to the ``auth``
    # header on a name clash, so it can't silently override real auth.
    headers: dict[str, str] = Field(default_factory=dict)
    # Static JSON request-body fields merged into every non-GET request. Combined
    # with ``forward_params_in: "body"`` this expresses a body-driven API — the
    # search term / store id / dynamic-key map land in the JSON body instead of
    # the query string. Ignored for GET (a GET carries no body).
    body: dict[str, Any] = Field(default_factory=dict)
    # Where a tool's forwarded params (REST passthrough ``rest_query_params`` and
    # the call-time params of a passthrough fetch) are placed:
    #   * "query" — appended to the URL query string (the default, GET-style).
    #   * "body"  — serialized into the JSON request body (POST/PUT/PATCH only),
    #               for APIs that read their inputs from the body, not the URL.
    forward_params_in: Literal["query", "body"] = "query"

    # DB (postgres / mysql)
    table: str | None = None
    query: str | None = None

    # File
    path: str | None = None
    format: Literal["csv", "json", "jsonl"] | None = None
    encoding: str = "utf-8"
    delimiter: str = ","
    # File — inline content. When set, the file's bytes travel WITH the source
    # (inside session.json and the published connector spec) instead of being
    # re-read from ``path`` on the host filesystem. This is what makes a file
    # source portable across the builder and the published runtime — which run
    # in different processes (and, in the cloud, different containers) with no
    # shared disk — and durable across restarts/evictions, where the builder's
    # workspace files are gone but the saved source must still materialize.
    # ``content`` is UTF-8 text by default, or base64 when
    # ``content_encoding == "base64"`` (binary / non-UTF-8 files).
    content: str | None = None
    content_encoding: Literal["text", "base64"] = "text"

    # Managed ("elliot") sources — data lives IN Elliot's per-connector store
    # (the system of record), not behind an external API/DB/file. The author
    # declares the schema here; WRITE tools insert/update/delete rows through
    # the tool's ``data_mapping`` and READ tools query it like any table.
    columns: list[ManagedColumn] = Field(default_factory=list)
    # When true (the default) every row is owned by the end user who wrote it:
    # reads are scoped to "my rows + rows shared with me" and mutations to
    # "my rows + rows whose owner granted me write access". False makes the
    # table app-wide — every authenticated user of the connector shares it.
    user_scoped: bool = True

    # Runtime tracking (populated after a fetch)
    table_name: str | None = None
    row_count: int | None = None
    config_snapshot: dict[str, Any] | None = None
    # Child tables produced by the flattener for nested arrays (e.g. a REST
    # response with ``orders[].line_items[]`` yields ``orders_line_items``).
    # Persisted so an agent can rediscover the full relational schema via
    # ``elliot_list_sources`` without re-fetching the source.
    related_tables: list[str] = Field(default_factory=list)


class FetchResult(BaseModel):
    rows: list[dict[str, Any]]
    fetched_at: str
    page_count: int = 1
    warnings: list[str] = []
    # Populated by passthrough fetcher so the agent knows how to get the next page.
    # Keys depend on pagination strategy: next_cursor, next_url, total, has_more, etc.
    pagination_meta: dict[str, Any] = {}
