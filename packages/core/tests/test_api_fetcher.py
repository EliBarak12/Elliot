"""Tests for api_fetcher: auth helpers, row extraction, and fetch_endpoint."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from elliot_core.errors import SourceFetchError
from elliot_core.sources.api_fetcher import (
    _build_auth_headers,
    _build_auth_query_params,
    _extract_rows,
    _parse_link_next,
    _resolve_secret,
    fetch_endpoint,
)
from elliot_core.types.source import AuthConfig, PaginationConfig, SourceConfig


def _source(
    url: str = "https://api.example.com/items",
    auth: AuthConfig | None = None,
    pagination: PaginationConfig | None = None,
    data_path: str | None = None,
) -> SourceConfig:
    return SourceConfig(
        id="src",
        name="Source",
        type="rest",
        url=url,
        auth=auth,
        pagination=pagination or PaginationConfig(strategy="none"),
        data_path=data_path,
    )


# ── _resolve_secret ───────────────────────────────────────────────────────────


def test_resolve_secret_env_var(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MY_KEY", "secret123")
    result = _resolve_secret("{{ env:MY_KEY }}", {})
    assert result == "secret123"


def test_resolve_secret_from_dict():
    result = _resolve_secret("my_token", {"my_token": "abc"})
    assert result == "abc"


def test_resolve_secret_literal_passthrough():
    result = _resolve_secret("literal-key", {})
    assert result == "literal-key"


# ── _build_auth_headers ───────────────────────────────────────────────────────


def test_build_auth_headers_none_returns_empty():
    src = _source()
    assert _build_auth_headers(src, {}) == {}


def test_build_auth_headers_bearer():
    auth = AuthConfig(type="bearer", secret_key="tok")
    headers = _build_auth_headers(_source(auth=auth), {"tok": "my-token"})
    assert headers["Authorization"] == "Bearer my-token"


def test_build_auth_headers_api_key():
    auth = AuthConfig(type="api_key", secret_key="tok", header_name="X-Api-Key")
    headers = _build_auth_headers(_source(auth=auth), {"tok": "k123"})
    assert headers["X-Api-Key"] == "k123"


def test_build_auth_headers_basic():
    import base64

    auth = AuthConfig(type="basic", secret_key="cred")
    headers = _build_auth_headers(_source(auth=auth), {"cred": "user:pass"})
    encoded = base64.b64encode(b"user:pass").decode()
    assert headers["Authorization"] == f"Basic {encoded}"


def test_build_auth_headers_no_auth():
    assert _build_auth_headers(_source(), {}) == {}


# ── _build_auth_query_params ──────────────────────────────────────────────────


def test_build_auth_query_params_api_key_query():
    auth = AuthConfig(type="api_key", secret_key="tok", query_param="api_key")
    params = _build_auth_query_params(_source(auth=auth), {"tok": "abc"})
    assert params["api_key"] == "abc"


def test_build_auth_query_params_bearer_returns_empty():
    auth = AuthConfig(type="bearer", secret_key="tok")
    assert _build_auth_query_params(_source(auth=auth), {"tok": "x"}) == {}


# ── _extract_rows ─────────────────────────────────────────────────────────────


def test_extract_rows_list_data():
    rows = _extract_rows([{"id": 1}], None)
    assert rows == [{"id": 1}]


def test_extract_rows_dict_with_data_key():
    rows = _extract_rows({"data": [{"id": 2}]}, None)
    assert rows == [{"id": 2}]


def test_extract_rows_dict_with_items_key():
    rows = _extract_rows({"items": [{"id": 3}]}, None)
    assert rows == [{"id": 3}]


def test_extract_rows_single_dict_wrapped():
    rows = _extract_rows({"id": 1}, None)
    assert rows == [{"id": 1}]


def test_extract_rows_with_data_path():
    data = {"meta": {"results": [{"id": 1}]}}
    rows = _extract_rows(data, "meta.results")
    assert rows == [{"id": 1}]


def test_extract_rows_data_path_not_found_returns_empty():
    rows = _extract_rows({"x": 1}, "missing.path")
    assert rows == []


# ── _parse_link_next ──────────────────────────────────────────────────────────


def test_parse_link_next_found():
    header = '<https://api.example.com/page2>; rel="next"'
    assert _parse_link_next(header) == "https://api.example.com/page2"


def test_parse_link_next_not_found():
    assert _parse_link_next('<https://api.example.com/page1>; rel="prev"') is None


# ── fetch_endpoint ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_simple():
    respx.get("https://api.example.com/items").mock(return_value=Response(200, json=[{"id": 1}]))
    result = await fetch_endpoint(_source(), {})
    assert result.rows == [{"id": 1}]
    assert result.page_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_http_error_raises():
    respx.get("https://api.example.com/items").mock(return_value=Response(500))
    with pytest.raises(SourceFetchError):
        await fetch_endpoint(_source(), {})


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_offset_pagination():
    respx.get("https://api.example.com/items").mock(
        side_effect=[
            Response(200, json=[{"id": i} for i in range(5)]),
            Response(200, json=[{"id": i} for i in range(5, 8)]),
        ]
    )
    pg = PaginationConfig(strategy="offset", page_size=5, max_pages=10)
    result = await fetch_endpoint(_source(pagination=pg), {})
    assert len(result.rows) == 8


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_page_pagination():
    respx.get("https://api.example.com/items").mock(
        side_effect=[
            Response(200, json=[{"id": i} for i in range(3)]),
            Response(200, json=[{"id": i} for i in range(3, 5)]),
        ]
    )
    pg = PaginationConfig(strategy="page", page_size=3, max_pages=10)
    result = await fetch_endpoint(_source(pagination=pg), {})
    assert len(result.rows) == 5


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_cursor_pagination():
    respx.get("https://api.example.com/items").mock(
        side_effect=[
            Response(200, json={"items": [{"id": 1}], "next_cursor": "tok123"}),
            Response(200, json={"items": [{"id": 2}]}),
        ]
    )
    pg = PaginationConfig(strategy="cursor", page_size=10, max_pages=10)
    src = _source(pagination=pg, data_path="items")
    result = await fetch_endpoint(src, {})
    assert len(result.rows) == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_link_header_pagination():
    call_count = 0

    def _handler(request: respx.models.Request) -> Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(
                200,
                json=[{"id": 1}],
                headers={"link": '<https://api.example.com/items?page=2>; rel="next"'},
            )
        return Response(200, json=[{"id": 2}])

    respx.get(url__startswith="https://api.example.com/items").mock(side_effect=_handler)
    pg = PaginationConfig(strategy="link_header", max_pages=10)
    result = await fetch_endpoint(_source(pagination=pg), {})
    assert len(result.rows) == 2


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_max_pages_warning():
    respx.get("https://api.example.com/items").mock(
        return_value=Response(200, json=[{"id": 1}, {"id": 2}])
    )
    pg = PaginationConfig(strategy="page", page_size=2, max_pages=1)
    result = await fetch_endpoint(_source(pagination=pg), {})
    assert any("max_pages" in w for w in result.warnings)
