from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["api_key", "bearer", "basic", "oauth2"]
    header_name: str | None = None
    query_param: str | None = None
    secret_key: str  # resolved via {{ env:VAR }} at load time


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
