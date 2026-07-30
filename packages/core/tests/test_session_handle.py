"""Tests for Elliot session handles — the app-level session on a stateless wire."""

from __future__ import annotations

from elliot_core.session_handle import (
    SESSION_HEADER,
    SessionHandle,
    get_current_session_handle,
    is_minted_handle,
    mint_session_handle,
    reset_current_session_handle,
    resolve_inbound,
    set_current_session_handle,
    upgrade_from_meta,
)


class TestMinting:
    def test_minted_shape(self) -> None:
        handle = mint_session_handle()
        assert is_minted_handle(handle)
        assert handle.startswith("es_") and len(handle) == 15

    def test_minted_handles_are_unique(self) -> None:
        assert mint_session_handle() != mint_session_handle()

    def test_foreign_ids_are_not_minted_shape(self) -> None:
        assert not is_minted_handle("sess-12345678")
        assert not is_minted_handle("es_notlowerhex!")


class TestResolveInbound:
    def test_explicit_header_wins(self) -> None:
        headers = {
            SESSION_HEADER.lower(): "es_abcdef123456",
            "mcp-session-id": "legacy-session-1",
        }
        handle = resolve_inbound(headers)
        assert handle == SessionHandle("es_abcdef123456", "header")

    def test_legacy_mcp_session_id_is_second(self) -> None:
        handle = resolve_inbound({"mcp-session-id": "legacy-session-1"})
        assert handle.value == "legacy-session-1"
        assert handle.source == "legacy"

    def test_mints_when_nothing_supplied(self) -> None:
        handle = resolve_inbound({})
        assert handle.source == "minted"
        assert is_minted_handle(handle.value)

    def test_malformed_client_value_is_ignored_and_minted(self) -> None:
        # Values that couldn't round-trip safely (spaces, control chars, too
        # short) never become correlation ids — a bad header must not break
        # or poison the journey.
        for bad in ("short", "has spaces here", "x" * 200, ""):
            handle = resolve_inbound({SESSION_HEADER.lower(): bad})
            assert handle.source == "minted"


class TestContextvarAndMetaUpgrade:
    def test_meta_upgrades_minted(self) -> None:
        token = set_current_session_handle(SessionHandle("es_aaaaaaaaaaaa", "minted"))
        try:
            upgraded = upgrade_from_meta("es_bbbbbbbbbbbb")
            assert upgraded is not None
            current = get_current_session_handle()
            assert current is not None
            assert current.value == "es_bbbbbbbbbbbb"
            assert current.source == "meta"
        finally:
            reset_current_session_handle(token)

    def test_header_outranks_meta(self) -> None:
        token = set_current_session_handle(SessionHandle("es_cccccccccccc", "header"))
        try:
            assert upgrade_from_meta("es_dddddddddddd") is None
            current = get_current_session_handle()
            assert current is not None and current.value == "es_cccccccccccc"
        finally:
            reset_current_session_handle(token)

    def test_same_value_is_not_an_upgrade(self) -> None:
        token = set_current_session_handle(SessionHandle("es_eeeeeeeeeeee", "minted"))
        try:
            assert upgrade_from_meta("es_eeeeeeeeeeee") is None
        finally:
            reset_current_session_handle(token)

    def test_non_string_meta_is_ignored(self) -> None:
        token = set_current_session_handle(SessionHandle("es_ffffffffffff", "minted"))
        try:
            assert upgrade_from_meta({"nested": "junk"}) is None
            assert upgrade_from_meta(None) is None
        finally:
            reset_current_session_handle(token)
