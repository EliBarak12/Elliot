"""Shared pagination engine for REST sources.

Two pure helpers used by BOTH the design-time fetcher (``api_fetcher``) and the
connector-runtime executor, so the page-walk can never drift between discovery
and live tool calls — historically these were copy-pasted and diverged.

Supports every ``PaginationConfig.strategy``:
  * ``none``        — single page.
  * ``offset``      — ``?offset=&limit=`` until a short page.
  * ``page``        — ``?page=`` until a short page.
  * ``cursor``      — ``?limit=`` plus the cursor under ``cursor_param``
                      (default ``cursor``). The next cursor comes from the last
                      record's ``cursor_record_field`` (Stripe: ``id``) or a
                      top-level ``next_cursor`` / ``cursor_field``. Stops when
                      ``has_more_field`` is false, the cursor is empty, or the
                      page is empty. This makes the common Stripe idiom
                      (``?limit=N&starting_after=<last_id>`` + ``has_more``)
                      expressible without special-casing any single API.
  * ``link_header`` — follow RFC 5988 ``Link: <…>; rel="next"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from elliot_core.types.source import PaginationConfig


def parse_link_next(link_header: str) -> str | None:
    """Extract the ``rel="next"`` URL from an RFC 5988 ``Link`` header."""
    m = re.search(r'<([^>]+)>;\s*rel="next"', link_header or "")
    return m.group(1) if m else None


@dataclass
class PageCursor:
    """Mutable position in a paginated walk. One instance per fetch."""

    page: int = 1
    offset: int = 0
    cursor: str | None = None
    next_url: str | None = None


def page_query_params(pg: PaginationConfig, state: PageCursor) -> dict[str, Any]:
    """Return the query params to add to the request for the current page.

    Auth/passthrough params are layered on by the caller; this only adds the
    pagination-specific keys for the active strategy.
    """
    params: dict[str, Any] = {}
    if pg.strategy == "offset":
        params["offset"] = state.offset
        params["limit"] = pg.page_size
    elif pg.strategy == "page":
        params["page"] = state.page
    elif pg.strategy == "cursor":
        params["limit"] = pg.page_size
        if state.cursor:
            params[pg.cursor_param] = state.cursor
    return params


def advance(
    pg: PaginationConfig,
    state: PageCursor,
    *,
    rows: list[dict[str, Any]],
    data: Any,
    link_header: str = "",
) -> bool:
    """Update ``state`` for the next page and report whether to continue.

    Call after the current page's ``rows`` have been appended and any row-cap
    check has run. ``data`` is the decoded response body; ``link_header`` the
    response's ``Link`` header (for ``link_header`` strategy). Returns ``True``
    to fetch another page, ``False`` to stop.
    """
    if pg.strategy == "none" or not rows:
        return False
    if pg.strategy == "offset":
        if len(rows) < pg.page_size:
            return False
        state.offset += pg.page_size
        return True
    if pg.strategy == "page":
        if len(rows) < pg.page_size:
            return False
        state.page += 1
        return True
    if pg.strategy == "cursor":
        # Explicit "no more pages" signal wins.
        if pg.has_more_field and isinstance(data, dict) and not data.get(pg.has_more_field):
            return False
        # Next cursor: last record's field (Stripe), else a top-level field.
        if pg.cursor_record_field and rows:
            state.cursor = rows[-1].get(pg.cursor_record_field)
        elif isinstance(data, dict):
            state.cursor = data.get("next_cursor") or data.get(pg.cursor_field or "cursor")
        else:
            state.cursor = None
        return bool(state.cursor)
    if pg.strategy == "link_header":
        state.next_url = parse_link_next(link_header)
        return bool(state.next_url)
    return False
