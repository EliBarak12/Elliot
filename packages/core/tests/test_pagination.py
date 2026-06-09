from dataclasses import dataclass

from elliot_core.sources.pagination import (
    next_cursor,
    pagination_request_params,
    parse_link_next,
)


@dataclass
class _Pag:
    strategy: str
    page_size: int = 50
    cursor_field: str | None = None


def test_parse_link_next_extracts_next_rel() -> None:
    header = '<https://api.example.com/x?page=2>; rel="next", <https://api.example.com/x?page=9>; rel="last"'
    assert parse_link_next(header) == "https://api.example.com/x?page=2"


def test_parse_link_next_none_when_absent() -> None:
    assert parse_link_next("") is None
    assert parse_link_next('<https://x/1>; rel="prev"') is None


def test_pagination_request_params_per_strategy() -> None:
    assert pagination_request_params(_Pag("offset"), offset=20, page=1, cursor=None) == {
        "offset": 20,
        "limit": 50,
    }
    assert pagination_request_params(_Pag("page"), offset=0, page=3, cursor=None) == {"page": 3}
    assert pagination_request_params(_Pag("cursor"), offset=0, page=1, cursor="abc") == {
        "cursor": "abc"
    }
    # Cursor strategy with no cursor yet, and "none"/link_header, emit nothing.
    assert pagination_request_params(_Pag("cursor"), offset=0, page=1, cursor=None) == {}
    assert pagination_request_params(_Pag("none"), offset=0, page=1, cursor=None) == {}


def test_next_cursor_prefers_next_cursor_then_field() -> None:
    assert next_cursor({"next_cursor": "n1"}, _Pag("cursor")) == "n1"
    assert next_cursor({"cursor": "c1"}, _Pag("cursor")) == "c1"
    assert next_cursor({"page_token": "p1"}, _Pag("cursor", cursor_field="page_token")) == "p1"
    assert next_cursor({}, _Pag("cursor")) is None
    assert next_cursor([1, 2, 3], _Pag("cursor")) is None
