"""Tests for elliot_core.secrets."""

from __future__ import annotations

import pytest

from elliot_core.secrets import SecretResolutionError, check_secrets, resolve_secrets


def test_resolve_replaces_placeholder(monkeypatch) -> None:
    monkeypatch.setenv("MY_KEY", "abc123")
    result = resolve_secrets({"auth": {"api_key": "{{ env:MY_KEY }}"}})
    assert result["auth"]["api_key"] == "abc123"


def test_resolve_raises_on_missing() -> None:
    with pytest.raises(SecretResolutionError, match="MY_MISSING"):
        resolve_secrets("{{ env:MY_MISSING }}")


def test_resolve_nested_list(monkeypatch) -> None:
    monkeypatch.setenv("HOST", "db.example.com")
    result = resolve_secrets(["pre-{{ env:HOST }}-post"])
    assert result[0] == "pre-db.example.com-post"


def test_resolve_non_string_passthrough() -> None:
    assert resolve_secrets(42) == 42
    assert resolve_secrets(True) is True
    assert resolve_secrets(None) is None


def test_resolve_no_placeholders(monkeypatch) -> None:
    result = resolve_secrets({"url": "https://example.com"})
    assert result["url"] == "https://example.com"


def test_check_secrets_returns_missing(monkeypatch) -> None:
    monkeypatch.delenv("GONE", raising=False)
    missing = check_secrets({"url": "{{ env:GONE }}"})
    assert "GONE" in missing


def test_check_secrets_empty_when_all_set(monkeypatch) -> None:
    monkeypatch.setenv("PRESENT", "value")
    missing = check_secrets({"url": "{{ env:PRESENT }}"})
    assert missing == []


def test_check_secrets_nested(monkeypatch) -> None:
    monkeypatch.delenv("A", raising=False)
    monkeypatch.delenv("B", raising=False)
    monkeypatch.setenv("C", "ok")
    missing = check_secrets(
        {
            "x": "{{ env:A }}",
            "nested": {"y": "{{ env:B }}", "z": "{{ env:C }}"},
            "list": ["{{ env:A }}"],
        }
    )
    assert set(missing) == {"A", "B"}
