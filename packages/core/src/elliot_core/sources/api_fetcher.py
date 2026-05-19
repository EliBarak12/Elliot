from __future__ import annotations

import asyncio
import base64
import os
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog

from elliot_core.errors import SourceFetchError
from elliot_core.http import SSRFError, safe_client, validate_url
from elliot_core.redaction import redact_url
from elliot_core.types.source import FetchResult, SourceConfig

log = structlog.get_logger(__name__)

_RETRY_STATUSES = {429, 500, 503}
_MAX_RETRIES = 3
# Total upstream-retry budget across the whole fetch call. `_MAX_RETRIES` is
# per page; without a global ceiling a many-page fetch against a flaky
# upstream amplifies into a large request count. Once this budget is spent we
# stop retrying and fail fast.
_MAX_TOTAL_RETRIES = 8

_DEFAULT_MAX_RESULT_ROWS = 10_000


def _max_rows() -> int:
    """Overall accumulated-row cap for a paginated fetch (env ELLIOT_MAX_RESULT_ROWS).

    Reuses the same env var the connector runtime's executor uses, so a single
    knob bounds both design-time and runtime fetches.
    """
    raw = os.environ.get("ELLIOT_MAX_RESULT_ROWS", "")
    try:
        return max(1, int(raw)) if raw else _DEFAULT_MAX_RESULT_ROWS
    except ValueError:
        return _DEFAULT_MAX_RESULT_ROWS


def _pinned_hosts(url: str, ips: list[str]) -> dict[str, str] | None:
    """Build a ``{hostname: validated_ip}`` map for `safe_client(pinned_hosts=)`."""
    host = urlsplit(url).hostname or ""
    return {host: ips[0]} if (host and ips) else None


_ENV_VAR_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _retry_after_seconds(value: str | None, fallback: float) -> float:
    """Parse a Retry-After header, which may be a delay in seconds or an
    HTTP-date. Falls back to ``fallback`` for missing/unparseable values."""
    if not value:
        return fallback
    try:
        return float(value)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        return fallback
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _resolve_secret(key: str, secrets: dict[str, str]) -> str:
    """Resolve ``auth.secret_key`` to the concrete secret value.

    Three forms are accepted:

    * ``"{{ env:NAME }}"`` — env-var template. Looks up ``NAME`` in the
      passed-in ``secrets`` dict, then in ``os.environ``.
    * ``"NAME"`` — bare env-var-shaped name (UPPER_SNAKE). Treated the same
      as the template form: secrets dict first (case-insensitive), then
      ``os.environ``. Falling back to the literal key for an env-var-shaped
      input was a UX trap — the bearer header silently became ``"Bearer
      NAME"`` and agents spent turns debugging "401 unauthorized".
    * Any other string — returned verbatim. This covers the case where
      ``elliot_core.secrets.resolve_secrets`` has already replaced a
      ``{{ env:VAR }}`` template at load time with the resolved value.
    """
    if key.startswith("{{ env:") and key.endswith(" }}"):
        env_var = key[len("{{ env:") : -len(" }}")].strip()
        return secrets.get(env_var) or secrets.get(env_var.lower()) or os.environ.get(env_var, "")
    if _ENV_VAR_NAME.match(key):
        return secrets.get(key) or secrets.get(key.lower()) or os.environ.get(key) or ""
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
    base_params: dict[str, Any] = _build_auth_query_params(config, secrets)
    pagination = config.pagination
    all_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    page_count = 0
    offset = 0
    page = 1
    cursor: str | None = None
    next_url: str | None = None
    # Global ceilings: total upstream retries (FIX 4) and accumulated rows
    # (FIX 3) across the whole paginated fetch.
    retry_budget = _MAX_TOTAL_RETRIES
    row_cap = _max_rows()

    # SSRF DNS-rebinding defense: validate the initial URL up front and pin
    # the connection pool to the vetted IP. A cross-host `next` link will fail
    # closed inside `_PinnedTransport` — acceptable, it's safe.
    initial_url = config.url or ""
    try:
        initial_ips = validate_url(initial_url)
    except SSRFError as exc:
        raise SourceFetchError(f"Refusing to fetch: {exc.message}") from exc
    pinned_hosts = _pinned_hosts(initial_url, initial_ips)

    async with safe_client(timeout=config.timeout_ms / 1000, pinned_hosts=pinned_hosts) as client:
        while True:
            if page_count >= pagination.max_pages:
                warnings.append(f"Reached max_pages limit ({pagination.max_pages})")
                break

            request_url = next_url or (config.url or "")
            # SSRF guard: validate every URL we're about to call. The initial
            # source.url comes from the connector definition; next_url comes
            # from the upstream response (e.g. rel="next") and is therefore
            # attacker-influenced.
            try:
                validate_url(request_url)
            except SSRFError as exc:
                raise SourceFetchError(f"Refusing to fetch: {exc.message}") from exc
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
                    # Retry only if both the per-page attempt limit AND the
                    # global retry budget allow it. The budget (FIX 4) caps
                    # total upstream retries across the whole paginated fetch
                    # so a flaky upstream can't amplify into a request storm.
                    if attempt == _MAX_RETRIES - 1:
                        raise SourceFetchError(
                            f"Network error fetching {redact_url(config.url)}: {type(exc).__name__}"
                        ) from exc
                    if retry_budget <= 0:
                        raise SourceFetchError(
                            f"Exhausted total retry budget ({_MAX_TOTAL_RETRIES}) "
                            f"fetching {redact_url(config.url)}"
                        ) from exc
                    retry_budget -= 1
                    await asyncio.sleep(2**attempt)
                    continue

                if resp.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                    if retry_budget <= 0:
                        raise SourceFetchError(
                            f"Exhausted total retry budget ({_MAX_TOTAL_RETRIES}) "
                            f"fetching {redact_url(config.url)}"
                        )
                    retry_budget -= 1
                    delay = min(
                        _retry_after_seconds(resp.headers.get("Retry-After"), 2**attempt), 30
                    )
                    await asyncio.sleep(delay)
                    continue
                break

            if resp is None or resp.is_error:
                status = resp.status_code if resp else 0
                raise SourceFetchError(
                    f"HTTP {status} from {redact_url(config.url)} after {_MAX_RETRIES} attempts"
                )

            data = resp.json()
            rows = _extract_rows(data, config.data_path)
            all_rows.extend(rows)
            page_count += 1

            # FIX 3: bound total memory — stop paginating once the accumulated
            # row count reaches the cap, and truncate to it.
            if len(all_rows) >= row_cap:
                if len(all_rows) > row_cap:
                    log.warning(
                        "api_fetcher.rows.truncated",
                        url=redact_url(config.url),
                        returned=row_cap,
                        accumulated=len(all_rows),
                    )
                    del all_rows[row_cap:]
                warnings.append(f"Reached max row cap ({row_cap}); result truncated")
                break

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
                cursor = (
                    data.get("next_cursor") or data.get(pagination.cursor_field or "cursor")
                    if isinstance(data, dict)
                    else None
                )
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
