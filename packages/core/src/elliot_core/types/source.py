from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class AuthConfig(BaseModel):
    type: Literal["api_key", "bearer", "basic", "oauth2"]
    header_name: Optional[str] = None
    query_param: Optional[str] = None
    secret_key: str  # resolved via {{ env:VAR }} at load time


class PaginationConfig(BaseModel):
    strategy: Literal["cursor", "offset", "page", "link_header", "none"] = "none"
    page_size: int = 100
    max_pages: int = 10
    cursor_field: Optional[str] = None
    next_url_field: Optional[str] = None


class SourceConfig(BaseModel):
    id: str
    name: str
    type: Literal["rest", "postgres", "mysql", "file"]

    # REST
    url: Optional[str] = None
    method: Literal["GET", "POST"] = "GET"
    auth: Optional[AuthConfig] = None
    pagination: PaginationConfig = PaginationConfig()
    data_path: Optional[str] = None  # jmespath to extract list from response
    timeout_ms: int = 30_000

    # DB (postgres / mysql)
    table: Optional[str] = None
    query: Optional[str] = None

    # File
    path: Optional[str] = None
    format: Optional[Literal["csv", "json", "jsonl"]] = None
    encoding: str = "utf-8"
    delimiter: str = ","


class FetchResult(BaseModel):
    rows: list[dict[str, Any]]
    fetched_at: str
    page_count: int = 1
    warnings: list[str] = []
