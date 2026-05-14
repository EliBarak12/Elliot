"""Tests for elliot_core.redaction (URL + dict scrubbing)."""

from __future__ import annotations

from elliot_core.redaction import redact_audit_arguments, redact_url, redact_value

# ── redact_url ────────────────────────────────────────────────────────────


def test_redact_url_strips_userinfo():
    assert redact_url("https://user:pass@api.example.com/path") == "https://api.example.com/path"


def test_redact_url_strips_only_userinfo_keeps_port():
    assert redact_url("http://u:p@host:8080/x") == "http://host:8080/x"


def test_redact_url_redacts_secret_query_params():
    out = redact_url("https://api.example.com/?api_key=abc123&other=ok")
    assert "api_key=***" in out
    assert "other=ok" in out
    assert "abc123" not in out


def test_redact_url_keeps_normal_url():
    assert redact_url("https://example.com/api/v1/items?limit=10") == (
        "https://example.com/api/v1/items?limit=10"
    )


def test_redact_url_handles_empty():
    assert redact_url("") == ""
    assert redact_url(None) == ""


def test_redact_url_case_insensitive_param():
    out = redact_url("https://x/?API_KEY=abc")
    assert "API_KEY=***" in out


# ── redact_value (dict scrubbing) ─────────────────────────────────────────


def test_redact_value_masks_top_level_secrets():
    out = redact_value({"api_key": "abc", "name": "x"})
    assert out == {"api_key": "***", "name": "x"}


def test_redact_value_masks_nested():
    out = redact_value({"auth": {"token": "xxx"}, "name": "x"})
    assert out["auth"]["token"] == "***"
    assert out["name"] == "x"


def test_redact_value_walks_lists():
    out = redact_value([{"password": "p1"}, {"name": "y"}])
    assert out[0]["password"] == "***"
    assert out[1]["name"] == "y"


def test_redact_value_truncates_huge_strings():
    huge = "x" * 1000
    out = redact_value(huge)
    assert isinstance(out, str)
    assert len(out) < len(huge)
    assert "[truncated]" in out


def test_redact_audit_arguments_alias():
    """`redact_audit_arguments` is the public entry point; should behave like redact_value."""
    out = redact_audit_arguments({"api_key": "x", "ok": "y"})
    assert out == {"api_key": "***", "ok": "y"}
