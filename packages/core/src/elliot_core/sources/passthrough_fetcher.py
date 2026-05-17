from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from elliot_core.errors import SourceFetchError
from elliot_core.http import SSRFError, safe_client, validate_url
from elliot_core.redaction import redact_url
from elliot_core.sources.api_fetcher import (
    _build_auth_headers,
    _build_auth_query_params,
    _extract_rows,
    _pinned_hosts,
)
from elliot_core.types.source import FetchResult, SourceConfig


async def fetch_passthrough(
    source: SourceConfig,
    secrets: dict[str, str],
    query_params: dict[str, Any],
) -> FetchResult:
    """
    Single-request fetch that forwards agent-supplied params directly to the API.
    No automatic pagination — the agent controls page/cursor/limit.

    Pagination metadata is extracted using the field names declared in
    source.pagination (cursor_field, next_url_field) so nothing is hardcoded.
    """
    headers = _build_auth_headers(source, secrets)
    base_params: dict[str, Any] = dict(_build_auth_query_params(source, secrets))
    base_params.update({k: v for k, v in query_params.items() if v is not None})

    target_url = source.url or ""
    # SSRF DNS-rebinding defense: validate the URL and pin the client's
    # connection to the vetted IP so a rebind between validate_url and the
    # request cannot redirect the socket to a private/metadata address.
    try:
        target_ips = validate_url(target_url)
    except SSRFError as exc:
        raise SourceFetchError(f"Refusing to fetch: {exc.message}") from exc
    pinned_hosts = _pinned_hosts(target_url, target_ips)

    try:
        async with safe_client(
            timeout=source.timeout_ms / 1000, pinned_hosts=pinned_hosts
        ) as client:
            resp = await client.request(
                method=source.method,
                url=target_url,
                params=base_params or None,
                headers=headers,
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SourceFetchError(
            f"HTTP {exc.response.status_code} from {redact_url(source.url)} (passthrough)"
        ) from exc
    except Exception as exc:
        raise SourceFetchError(
            f"Network error fetching {redact_url(source.url)}: {type(exc).__name__}"
        ) from exc

    data = resp.json()
    rows = _extract_rows(data, source.data_path)
    pagination_meta = _extract_pagination_meta(data, resp.headers, source)

    return FetchResult(
        rows=rows,
        fetched_at=datetime.now(UTC).isoformat(),
        page_count=1,
        pagination_meta=pagination_meta,
    )


def _extract_pagination_meta(
    data: Any,
    headers: httpx.Headers,
    source: SourceConfig,
) -> dict[str, Any]:
    """
    Extract next-page information using the field names declared in
    source.pagination — not a hardcoded list of guesses.
    """
    meta: dict[str, Any] = {}
    pg = source.pagination

    if not isinstance(data, dict):
        return meta

    if pg.strategy == "cursor" and pg.cursor_field:
        val = data.get(pg.cursor_field)
        if val is not None:
            meta["next_cursor"] = val
            meta["cursor_field"] = pg.cursor_field

    elif pg.strategy == "link_header":
        import re

        link = headers.get("link", "")
        m = re.search(r'<([^>]+)>;\s*rel="next"', link)
        if m:
            meta["next_url"] = m.group(1)

    elif pg.strategy in ("page", "offset") and pg.next_url_field:
        val = data.get(pg.next_url_field)
        if val is not None:
            meta["next_url"] = val

    # Surface row totals if the API provides them (field names vary per API,
    # but these are universally useful — the agent can use them for UI or planning)
    for key in ("total", "total_count", "count", "has_more"):
        if key in data:
            meta[key] = data[key]

    return meta
