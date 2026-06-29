"""Tests for api_fetcher: auth helpers, row extraction, and fetch_endpoint."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from elliot_core.errors import SourceFetchError
from elliot_core.sources.api_fetcher import (
    _build_auth_headers,
    _build_auth_query_params,
    _build_custom_headers,
    _extract_rows,
    _parse_link_next,
    _request_headers,
    _resolve_secret,
    _sanitize_header_value,
    _split_params_and_body,
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


def test_build_auth_headers_override_wins_for_oauth2():
    auth = AuthConfig(type="oauth2", secret_key="{{ user_oauth:acme }}")
    headers = _build_auth_headers(_source(auth=auth), {}, "live-token")
    assert headers["Authorization"] == "Bearer live-token"


def test_build_auth_headers_override_ignored_for_api_key():
    # An override is a bearer token; it must not hijack api_key header injection.
    auth = AuthConfig(type="api_key", secret_key="tok", header_name="X-Api-Key")
    headers = _build_auth_headers(_source(auth=auth), {"tok": "k123"}, "live-token")
    assert headers == {"X-Api-Key": "k123"}


@respx.mock
async def test_fetch_endpoint_uses_auth_token_override():
    route = respx.get("https://api.example.com/items").mock(
        return_value=Response(200, json=[{"id": 1}])
    )
    auth = AuthConfig(type="oauth2", secret_key="{{ user_oauth:acme }}")
    await fetch_endpoint(_source(auth=auth), {}, auth_token_override="live-token")
    assert route.calls.last.request.headers["Authorization"] == "Bearer live-token"


# ── header sanitization (F6) + custom headers + body framing ──────────────────


def test_sanitize_header_value_strips_crlf_and_whitespace():
    assert _sanitize_header_value("  tok123\n") == "tok123"
    assert _sanitize_header_value("a\r\nb") == "ab"


def test_bearer_secret_with_trailing_newline_is_sanitized():
    # F6: a token resolved with a stray newline previously made httpx/h11 raise
    # LocalProtocolError before the request left the client. Sanitizing the
    # header value turns that crash into a well-formed Authorization header.
    auth = AuthConfig(type="bearer", secret_key="tok")
    headers = _build_auth_headers(_source(auth=auth), {"tok": "my-token\n"})
    assert headers["Authorization"] == "Bearer my-token"


def _src_with(**kw: object) -> SourceConfig:
    base: dict[str, object] = {
        "id": "src",
        "name": "Source",
        "type": "rest",
        "url": "https://api.example.com/items",
    }
    base.update(kw)
    return SourceConfig.model_validate(base)


def test_build_custom_headers_resolves_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ECOMTOKEN", "ecom-123")
    src = _src_with(headers={"ecomtoken": "{{ env:ECOMTOKEN }}", "locale": "he"})
    headers = _build_custom_headers(src, {})
    assert headers == {"ecomtoken": "ecom-123", "locale": "he"}


def test_build_custom_headers_skips_blank_name():
    src = _src_with(headers={"  ": "x", "ok": "y"})
    assert _build_custom_headers(src, {}) == {"ok": "y"}


def test_request_headers_auth_wins_over_custom():
    # A custom header named Authorization must not override the real auth scheme.
    auth = AuthConfig(type="bearer", secret_key="tok")
    src = _src_with(auth=auth, headers={"Authorization": "Bearer spoof", "x-extra": "1"})
    headers = _request_headers(src, {"tok": "real"})
    assert headers["Authorization"] == "Bearer real"
    assert headers["x-extra"] == "1"


def test_split_params_query_mode_default():
    src = _src_with(method="POST")
    query, body = _split_params_and_body(src, {"key": "k"}, {"q": "x", "skip": None})
    assert query == {"key": "k", "q": "x"}
    assert body is None


def test_split_params_body_mode_merges_static_body():
    src = _src_with(method="POST", forward_params_in="body", body={"aggs": 1})
    query, body = _split_params_and_body(src, {"key": "k"}, {"q": "x", "skip": None})
    assert query == {"key": "k"}
    assert body == {"aggs": 1, "q": "x"}


def test_split_params_get_never_sends_body():
    # forward_params_in="body" on a GET is meaningless — params stay on query.
    src = _src_with(method="GET", forward_params_in="body", body={"aggs": 1})
    query, body = _split_params_and_body(src, {}, {"q": "x"})
    assert query == {"q": "x"}
    assert body is None


@respx.mock
async def test_fetch_endpoint_forwards_params_to_body():
    import json

    route = respx.post("https://api.example.com/items").mock(
        return_value=Response(200, json=[{"id": 1}])
    )
    src = _src_with(
        method="POST",
        forward_params_in="body",
        body={"store": "331"},
        pagination=PaginationConfig(strategy="none"),
    )
    await fetch_endpoint(src, {}, extra_params={"q": "cottage"})
    req = route.calls.last.request
    assert json.loads(req.content) == {"store": "331", "q": "cottage"}
    assert req.url.query == b""


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


def test_extract_rows_autodetects_resource_named_array():
    # dummyjson-style envelope: pagination scalars + one resource-named array.
    # No explicit data_path and no standard key, but there's exactly one
    # list-of-objects field, so it must be extracted (not returned as 1 row).
    data = {"total": 100, "skip": 0, "limit": 30, "products": [{"id": 1}, {"id": 2}]}
    rows = _extract_rows(data, None)
    assert rows == [{"id": 1}, {"id": 2}]


def test_extract_rows_ambiguous_multiple_arrays_wraps_whole():
    # Two object-lists -> ambiguous; fall back to wrapping the whole envelope
    # rather than guessing wrong.
    data = {"products": [{"id": 1}], "categories": [{"id": 2}]}
    rows = _extract_rows(data, None)
    assert rows == [data]


def test_extract_rows_ignores_scalar_array():
    # A list of scalars (e.g. an "ids" array) is not a row set.
    data = {"name": "x", "tags": ["a", "b"]}
    rows = _extract_rows(data, None)
    assert rows == [data]


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
async def test_fetch_endpoint_extracts_nested_envelope():
    # CKAN-style: rows nested under result.results, no data_path configured.
    respx.get("https://api.example.com/items").mock(
        return_value=Response(
            200, json={"success": True, "result": {"results": [{"id": 1}, {"id": 2}]}}
        )
    )
    result = await fetch_endpoint(_source(), {})
    assert result.rows == [{"id": 1}, {"id": 2}]
    assert result.warnings == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_warns_on_unextracted_envelope():
    # Two candidate arrays -> can't auto-pick -> wrapped as one row + warning.
    respx.get("https://api.example.com/items").mock(
        return_value=Response(200, json={"orders": [{"id": 1}], "customers": [{"id": 2}]})
    )
    result = await fetch_endpoint(_source(), {})
    assert any("data_path" in w for w in result.warnings)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_endpoint_max_pages_warning():
    respx.get("https://api.example.com/items").mock(
        return_value=Response(200, json=[{"id": 1}, {"id": 2}])
    )
    pg = PaginationConfig(strategy="page", page_size=2, max_pages=1)
    result = await fetch_endpoint(_source(pagination=pg), {})
    assert any("max_pages" in w for w in result.warnings)


# ── FIX 3: overall accumulated-row cap ────────────────────────────────────


@respx.mock
async def test_fetch_endpoint_row_cap_truncates(monkeypatch: pytest.MonkeyPatch):
    """A source with huge pages is truncated at ELLIOT_MAX_RESULT_ROWS even
    before max_pages bites — bounds worker memory."""
    monkeypatch.setenv("ELLIOT_MAX_RESULT_ROWS", "5")
    # Each page returns a full page_size of rows so pagination would continue.
    respx.get("https://api.example.com/items").mock(
        return_value=Response(200, json=[{"id": i} for i in range(10)])
    )
    pg = PaginationConfig(strategy="page", page_size=10, max_pages=50)
    result = await fetch_endpoint(_source(pagination=pg), {})
    assert len(result.rows) == 5
    assert any("row cap" in w for w in result.warnings)
    # Truncation must stop pagination — only one upstream page was fetched.
    assert result.page_count == 1


# ── FIX 4: total upstream-retry budget ────────────────────────────────────


async def _no_sleep(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
    """Patch-in for asyncio.sleep so retry tests don't actually wait."""
    return None


@respx.mock
async def test_fetch_endpoint_total_retry_budget(monkeypatch: pytest.MonkeyPatch):
    """A fetch against a flaky upstream stops once the global retry budget is
    spent rather than amplifying retries indefinitely. With a budget of 1, the
    second retry exhausts it and the fetch fails fast with a clear message."""
    monkeypatch.setattr("elliot_core.sources.api_fetcher._MAX_TOTAL_RETRIES", 1)
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    # Always 503 — every attempt would otherwise be retried.
    route = respx.get("https://api.example.com/items").mock(return_value=Response(503))
    pg = PaginationConfig(strategy="page", page_size=2, max_pages=50)
    with pytest.raises(SourceFetchError) as exc:
        await fetch_endpoint(_source(pagination=pg), {})
    assert "retry budget" in str(exc.value)
    # Budget 1 => initial request + exactly one retry, then fail fast.
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_odata_pagination_follows_next_link() -> None:
    # P3: OData snapshots used to cap at the server page size because
    # @odata.nextLink was ignored.
    respx.get("https://api.example.com/items").mock(
        side_effect=[
            Response(
                200,
                json={
                    "value": [{"id": 1}, {"id": 2}],
                    "@odata.nextLink": "https://api.example.com/items?$skiptoken=2",
                },
            ),
            Response(200, json={"value": [{"id": 3}]}),
        ]
    )
    src = _source(
        pagination=PaginationConfig(strategy="odata", max_pages=10),
        data_path="value",
    )
    result = await fetch_endpoint(src, {})
    assert [r["id"] for r in result.rows] == [1, 2, 3]
    assert result.page_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_odata_next_link_without_strategy_warns() -> None:
    respx.get("https://api.example.com/items").mock(
        return_value=Response(
            200,
            json={
                "value": [{"id": 1}],
                "@odata.nextLink": "https://api.example.com/items?$skiptoken=2",
            },
        )
    )
    src = _source(pagination=PaginationConfig(strategy="none"), data_path="value")
    result = await fetch_endpoint(src, {})
    assert any("@odata.nextLink" in w for w in result.warnings)
