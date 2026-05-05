from __future__ import annotations

import asyncio
import base64
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from elliot_core.errors import SourceFetchError
from elliot_core.types.source import FetchResult, SourceConfig

_RETRY_STATUSES = {429, 500, 503}
_MAX_RETRIES = 3


def _resolve_secret(key: str, secrets: dict[str, str]) -> str:
    if key.startswith("{{ env:") and key.endswith(" }}"):
        import os

        env_var = key[7:-3].strip()
        return secrets.get(env_var) or os.environ.get(env_var, "")
    return secrets.get(key, key)


def _build_auth_headers(config: SourceConfig, secrets: dict[str, str]) -> dict[str, str]:
    if not config.auth:
        return {}
    auth = config.auth
    secret = _resolve_secret(auth.secret_key, secrets)
    if auth.type == "bearer":
        return {"Authorization": f"Bearer {secret}"}
    if auth.type == "api_key" and auth.header_name:
        return {auth.header_name: secret}
    if auth.type == "basic":
        encoded = base64.b64encode(secret.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}
    return {}


def _build_auth_query_params(config: SourceConfig, secrets: dict[str, str]) -> dict[str, str]:
    if config.auth and config.auth.type == "api_key" and config.auth.query_param:
        return {config.auth.query_param: _resolve_secret(config.auth.secret_key, secrets)}
    return {}


def _extract_rows(data: Any, data_path: str | None) -> list[dict[str, Any]]:
    if data_path:
        import jmespath

        extracted = jmespath.search(data_path, data)
        return extracted if isinstance(extracted, list) else ([extracted] if extracted else [])
    if isinstance(data, list):
        return data
    for key in ("data", "items", "results", "records", "rows"):
        if isinstance(data, dict) and isinstance(data.get(key), list):
            return data[key]
    return [data] if isinstance(data, dict) else []


def _parse_link_next(link_header: str) -> str | None:
    m = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
    return m.group(1) if m else None


async def fetch_endpoint(config: SourceConfig, secrets: dict[str, str]) -> FetchResult:
    headers = _build_auth_headers(config, secrets)
    base_params: dict[str, Any] = _build_auth_query_params(config, secrets)  # type: ignore[assignment]
    pagination = config.pagination
    all_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    page_count = 0
    offset = 0
    page = 1
    cursor: str | None = None
    next_url: str | None = None

    async with httpx.AsyncClient(timeout=config.timeout_ms / 1000) as client:
        while True:
            if page_count >= pagination.max_pages:
                warnings.append(f"Reached max_pages limit ({pagination.max_pages})")
                break

            request_url = next_url or (config.url or "")
            request_params: dict[str, Any] = dict(base_params)

            if pagination.strategy == "offset":
                request_params["offset"] = offset
                request_params["limit"] = pagination.page_size
            elif pagination.strategy == "page":
                request_params["page"] = page
            elif pagination.strategy == "cursor" and cursor:
                request_params["cursor"] = cursor

            resp: httpx.Response | None = None
            for attempt in range(_MAX_RETRIES):
                try:
                    resp = await client.request(
                        method=config.method,
                        url=request_url,
                        params=request_params or None,
                        headers=headers,
                    )
                except httpx.TransportError as exc:
                    if attempt == _MAX_RETRIES - 1:
                        raise SourceFetchError(
                            f"Network error fetching {config.url}: {type(exc).__name__}"
                        ) from exc
                    await asyncio.sleep(2**attempt)
                    continue

                if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                    delay = min(float(resp.headers.get("Retry-After", 2**attempt)), 30)
                    await asyncio.sleep(delay)
                    continue
                break

            if resp is None or resp.is_error:
                status = resp.status_code if resp else 0
                raise SourceFetchError(
                    f"HTTP {status} from {config.url} after {_MAX_RETRIES} attempts"
                )

            data = resp.json()
            rows = _extract_rows(data, config.data_path)
            all_rows.extend(rows)
            page_count += 1

            if pagination.strategy == "none" or not rows:
                break
            elif pagination.strategy == "offset":
                if len(rows) < pagination.page_size:
                    break
                offset += pagination.page_size
            elif pagination.strategy == "page":
                if len(rows) < pagination.page_size:
                    break
                page += 1
            elif pagination.strategy == "cursor":
                cursor = data.get("next_cursor") or data.get(pagination.cursor_field or "cursor")
                if not cursor:
                    break
            elif pagination.strategy == "link_header":
                next_url = _parse_link_next(resp.headers.get("link", ""))
                if not next_url:
                    break
            else:
                break

    return FetchResult(
        rows=all_rows,
        fetched_at=datetime.now(UTC).isoformat(),
        page_count=page_count,
        warnings=warnings,
    )
