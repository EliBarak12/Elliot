"""Unit tests for the shared pagination engine (used by both api_fetcher and
the connector-runtime executor)."""

from __future__ import annotations

from elliot_core.sources.pagination import (
    PageCursor,
    advance,
    page_query_params,
    parse_link_next,
)
from elliot_core.types.source import PaginationConfig


def _pg(**kw: object) -> PaginationConfig:
    return PaginationConfig(**kw)  # type: ignore[arg-type]


def test_parse_link_next():
    assert parse_link_next('<https://x/y?page=2>; rel="next"') == "https://x/y?page=2"
    assert parse_link_next('<https://x>; rel="prev"') is None
    assert parse_link_next("") is None


def test_none_stops_immediately():
    pg = _pg(strategy="none")
    assert advance(pg, PageCursor(), rows=[{"id": 1}], data={}) is False


def test_offset_params_and_advance():
    pg = _pg(strategy="offset", page_size=2)
    st = PageCursor()
    assert page_query_params(pg, st) == {"offset": 0, "limit": 2}
    assert advance(pg, st, rows=[{"id": 1}, {"id": 2}], data=[]) is True
    assert st.offset == 2
    # short page stops
    assert advance(pg, st, rows=[{"id": 3}], data=[]) is False


def test_page_params_and_advance():
    pg = _pg(strategy="page", page_size=2)
    st = PageCursor()
    assert page_query_params(pg, st) == {"page": 1}
    assert advance(pg, st, rows=[{"id": 1}, {"id": 2}], data=[]) is True
    assert st.page == 2


def test_cursor_stripe_style():
    # ?limit=&starting_after=<last id>, terminate on has_more=false.
    pg = _pg(
        strategy="cursor",
        cursor_param="starting_after",
        cursor_record_field="id",
        has_more_field="has_more",
        page_size=2,
    )
    st = PageCursor()
    assert page_query_params(pg, st) == {"limit": 2}  # no cursor on first page
    cont = advance(pg, st, rows=[{"id": "a"}, {"id": "b"}], data={"has_more": True})
    assert cont is True and st.cursor == "b"
    assert page_query_params(pg, st) == {"limit": 2, "starting_after": "b"}
    # has_more false -> stop
    assert advance(pg, st, rows=[{"id": "c"}], data={"has_more": False}) is False


def test_cursor_top_level_field_fallback():
    pg = _pg(strategy="cursor", cursor_field="next_cursor", page_size=2)
    st = PageCursor()
    assert advance(pg, st, rows=[{"id": 1}], data={"next_cursor": "tok2"}) is True
    assert st.cursor == "tok2"
    assert advance(pg, st, rows=[{"id": 2}], data={"next_cursor": None}) is False


def test_link_header_strategy():
    pg = _pg(strategy="link_header")
    st = PageCursor()
    cont = advance(
        pg, st, rows=[{"id": 1}], data=[], link_header='<https://x/y?page=2>; rel="next"'
    )
    assert cont is True and st.next_url == "https://x/y?page=2"
    assert advance(pg, st, rows=[{"id": 2}], data=[], link_header="") is False
