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
    # A nested non-sensitive key still has its sensitive children redacted.
    out = redact_value({"settings": {"token": "xxx"}, "name": "x"})
    assert out["settings"]["token"] == "***"
    assert out["name"] == "x"


def test_redact_value_masks_whole_sensitive_subtree():
    """A key that itself matches a sensitive substring (``auth``) is redacted
    wholesale — its value (dict or otherwise) is replaced, not descended into."""
    out = redact_value({"auth": {"token": "xxx"}, "name": "x"})
    assert out["auth"] == "***"
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


# ── expanded sensitive-key coverage ───────────────────────────────────────


def test_redact_value_masks_expanded_exact_keys():
    """Keys added to the expanded blocklist must be redacted."""
    payload = {
        "private_key": "p",
        "db_password": "d",
        "client_secret": "c",
        "access_token": "a",
        "refresh_token": "r",
        "x-api-token": "t",
        "name": "keep",
    }
    out = redact_value(payload)
    for k in payload:
        if k == "name":
            assert out[k] == "keep"
        else:
            assert out[k] == "***", k


def test_redact_value_substring_match_case_insensitive():
    """Any key CONTAINING a sensitive token is redacted, regardless of case."""
    out = redact_value(
        {
            "Stripe_Secret": "s",
            "USER_PASSWORD": "p",
            "oauth_access_token": "o",
            "myApiKeyValue": "k",
            "Authorization": "z",
            "normal_field": "ok",
        }
    )
    assert out["Stripe_Secret"] == "***"
    assert out["USER_PASSWORD"] == "***"
    assert out["oauth_access_token"] == "***"
    assert out["myApiKeyValue"] == "***"
    assert out["Authorization"] == "***"
    assert out["normal_field"] == "ok"


def test_redact_url_redacts_expanded_query_params():
    out = redact_url("https://x/?access_token=abc&client_secret=def&keep=ok")
    assert "access_token=***" in out
    assert "client_secret=***" in out
    assert "keep=ok" in out
    assert "abc" not in out
    assert "def" not in out
