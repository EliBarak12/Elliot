from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from elliot_core.errors import ElliotError, SourceFetchError
from elliot_core.sources.api_fetcher import (
    _build_auth_headers,
    _build_auth_query_params,
    _extract_rows,
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
    """
    headers = _build_auth_headers(source, secrets)
    base_params: dict[str, Any] = dict(_build_auth_query_params(source, secrets))  # type: ignore[arg-type]
    base_params.update({k: v for k, v in query_params.items() if v is not None})

    try:
        async with httpx.AsyncClient(timeout=source.timeout_ms / 1000) as client:
            resp = await client.request(
                method=source.method,
                url=source.url or "",
                params=base_params or None,
                headers=headers,
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SourceFetchError(
            f"HTTP {exc.response.status_code} from {source.url} (passthrough)"
        ) from exc
    except Exception as exc:
        raise SourceFetchError(
            f"Network error fetching {source.url}: {type(exc).__name__}"
        ) from exc

    data = resp.json()
    rows = _extract_rows(data, source.data_path)

    # Surface pagination metadata from the response if present
    meta_keys = ("total", "total_count", "total_pages", "has_more", "next_cursor", "next_page")
    pagination_meta = {
        k: data[k] for k in meta_keys if isinstance(data, dict) and k in data
    }

    return FetchResult(
        rows=rows,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        page_count=1,
        warnings=(
            [f"pagination_meta:{pagination_meta}"] if pagination_meta else []
        ),
    )
