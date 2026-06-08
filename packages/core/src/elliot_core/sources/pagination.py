"""REST pagination helpers shared by the design-time fetcher and the runtime.

Both ``elliot_core.sources.api_fetcher`` (build-time sampling) and the
connector runtime's executor paginate REST sources the same way — offset,
page, cursor, or RFC 5988 ``Link`` headers — so the per-strategy logic lives
here to keep the two from drifting.
"""

from __future__ import annotations

import re
from typing import Any

_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def parse_link_next(link_header: str) -> str | None:
    """Return the next URL from an RFC 5988 ``Link: <url>; rel="next"`` header."""
    m = _LINK_NEXT_RE.search(link_header)
    return m.group(1) if m else None


def pagination_request_params(
    pagination: Any, *, offset: int, page: int, cursor: str | None
) -> dict[str, Any]:
    """Build the query params for the current page given the pagination strategy.

    The caller layers these on top of any base/auth params; cursor params are
    only emitted once a cursor has been captured from a prior page.
    """
    if pagination.strategy == "offset":
        return {"offset": offset, "limit": pagination.page_size}
    if pagination.strategy == "page":
        return {"page": page}
    if pagination.strategy == "cursor" and cursor:
        return {"cursor": cursor}
    return {}


def next_cursor(envelope: Any, pagination: Any) -> str | None:
    """Read the next cursor from a response envelope, preferring ``next_cursor``
    then the configured ``cursor_field`` (default ``cursor``). None when the
    envelope is not a dict or carries no cursor."""
    if not isinstance(envelope, dict):
        return None
    return envelope.get("next_cursor") or envelope.get(pagination.cursor_field or "cursor")
