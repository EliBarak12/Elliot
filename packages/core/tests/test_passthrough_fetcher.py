"""Tests for passthrough_fetcher: single-request API fetches."""

from __future__ import annotations

import pytest
import respx
from httpx import Headers, Response

from elliot_core.errors import SourceFetchError
from elliot_core.sources.passthrough_fetcher import _extract_pagination_meta, fetch_passthrough
from elliot_core.types.source import PaginationConfig, SourceConfig


def _source(
    url: str = "https://api.example.com/items",
    pagination: PaginationConfig | None = None,
) -> SourceConfig:
    return SourceConfig(
        id="src",
        name="Source",
        type="rest",
        url=url,
        pagination=pagination or PaginationConfig(),
    )


# ── fetch_passthrough ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_fetch_passthrough_list_response():
    respx.get("https://api.example.com/items").mock(
        return_value=Response(200, json=[{"id": 1}, {"id": 2}])
    )
    result = await fetch_passthrough(_source(), {}, {})
    assert result.rows == [{"id": 1}, {"id": 2}]
    assert result.page_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_passthrough_forwards_query_params():
    route = respx.get("https://api.example.com/items").mock(return_value=Response(200, json=[]))
    await fetch_passthrough(_source(), {}, {"q": "widget", "page": 2})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_fetch_passthrough_http_error_raises():
    respx.get("https://api.example.com/items").mock(return_value=Response(500))
    with pytest.raises(SourceFetchError) as exc_info:
        await fetch_passthrough(_source(), {}, {})
    assert "500" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_passthrough_network_error_raises():
    respx.get("https://api.example.com/items").mock(side_effect=Exception("timeout"))
    with pytest.raises(SourceFetchError) as exc_info:
        await fetch_passthrough(_source(), {}, {})
    assert "Network error" in str(exc_info.value)


# ── _extract_pagination_meta ──────────────────────────────────────────────────


def test_pagination_meta_cursor_strategy():
    pg = PaginationConfig(strategy="cursor", cursor_field="next_cursor")
    data = {"items": [], "next_cursor": "abc123"}
    meta = _extract_pagination_meta(data, Headers(), _source(pagination=pg))
    assert meta["next_cursor"] == "abc123"


def test_pagination_meta_link_header_strategy():
    pg = PaginationConfig(strategy="link_header")
    headers = Headers({"link": '<https://api.example.com/items?page=2>; rel="next"'})
    meta = _extract_pagination_meta({}, headers, _source(pagination=pg))
    assert meta["next_url"] == "https://api.example.com/items?page=2"


def test_pagination_meta_page_strategy_with_next_url_field():
    pg = PaginationConfig(strategy="page", next_url_field="next")
    data = {"next": "https://api.example.com/items?page=2", "total": 100}
    meta = _extract_pagination_meta(data, Headers(), _source(pagination=pg))
    assert meta["next_url"] == "https://api.example.com/items?page=2"
    assert meta["total"] == 100


def test_pagination_meta_non_dict_data():
    pg = PaginationConfig(strategy="cursor", cursor_field="cursor")
    meta = _extract_pagination_meta([1, 2, 3], Headers(), _source(pagination=pg))
    assert meta == {}


def test_pagination_meta_has_more_surfaced():
    pg = PaginationConfig()
    data = {"items": [], "has_more": True, "count": 50}
    meta = _extract_pagination_meta(data, Headers(), _source(pagination=pg))
    assert meta["has_more"] is True
    assert meta["count"] == 50


@pytest.mark.asyncio
@respx.mock
async def test_passthrough_error_reports_constructed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # P2: a failed passthrough must name the URL the caller's params produced
    # (overridden resource_id), not the base source's baked-in one — and must
    # never leak the injected auth key.
    from elliot_core.types.source import AuthConfig

    monkeypatch.setenv("CKAN_KEY", "super-secret-123")
    auth = AuthConfig(type="api_key", query_param="key", secret_key="{{ env:CKAN_KEY }}")
    src = SourceConfig(
        id="ckan",
        name="ckan",
        type="rest",
        url="https://api.example.com/search?resource_id=BAKED&limit=5",
        auth=auth,
        pagination=PaginationConfig(),
    )
    respx.get("https://api.example.com/search").mock(return_value=Response(404))

    with pytest.raises(SourceFetchError) as excinfo:
        await fetch_passthrough(src, {}, {"resource_id": "REAL-XYZ", "limit": 100})

    msg = str(excinfo.value)
    assert "REAL-XYZ" in msg
    assert "BAKED" not in msg
    assert "super-secret-123" not in msg
