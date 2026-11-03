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


def test_redact_value_masks_secret_under_benign_key():
    """A secret-shaped value is redacted even under a non-sensitive key name."""
    jwt = "eyJhbGciOiJIUzI1Ni, dummy".replace(", dummy", "") + "." + "eyJzdWIiOiIxMjM0NTY3" + ".sig"
    out = redact_value({"note": jwt, "comment": "all fine here"})
    assert out["note"] == "***"
    assert out["comment"] == "all fine here"


def test_redact_value_masks_known_token_prefixes():
    out = redact_value(["sk-ABCDEFGHIJKLMNOP1234", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", "fine"])
    assert out[0] == "***"
    assert out[1] == "***"
    assert out[2] == "fine"


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


# ── what an owner may see of a call: metadata, not people's data ─────────────


def test_describe_value_says_what_not_what_it_says():
    from elliot_core.redaction import describe_value

    assert describe_value("Rex Carter") == "‹text · 10 chars›"
    assert describe_value(True) == "‹true›" and describe_value(False) == "‹false›"
    assert describe_value(3.5) == "‹number›"
    assert describe_value({"a": 1, "b": 2}) == "‹object · 2 keys›"
    assert describe_value([1, 2, 3]) == "‹list · 3 items›"
    assert describe_value(None) == "‹empty›"
    assert describe_value(b"x") == "‹bytes›"


def test_mask_call_arguments_keeps_only_values_that_identify_no_one():
    from elliot_core.redaction import mask_call_arguments

    masked = mask_call_arguments(
        {
            "search_text": "rex@example.com",
            "tier": "gold",
            "limit": 20,
            "confirm": True,
            "since": "1990-04-01",
            "filters": {"city": "Haifa"},
            "api_key": "sk_live_abcdef",
            "note": None,
        },
        keep={"tier"},
    )
    assert masked == {
        "search_text": "‹text · 15 chars›",
        "tier": "gold",
        "limit": 20,
        "confirm": True,
        "since": "‹text · 10 chars›",
        "filters": "‹object · 1 keys›",
        "api_key": "***",
        "note": None,
    }
    assert mask_call_arguments(["not", "a", "dict"]) == ["not", "a", "dict"]


def test_result_shape_counts_fields_and_types_never_values():
    from elliot_core.redaction import result_shape

    shape = result_shape(
        [
            {"name": "Rex", "age": 31, "tags": ["a"], "meta": {"k": 1}, "vip": True, "x": None},
            {"name": "", "age": "unknown", "tags": [], "meta": {}, "vip": False, "x": None},
            "not a row",
        ]
    )
    assert shape == {
        "rows": 3,
        "fields": [
            {"name": "name", "type": "text", "filled": 1},
            {"name": "age", "type": "mixed", "filled": 2},
            {"name": "tags", "type": "list", "filled": 1},
            {"name": "meta", "type": "object", "filled": 1},
            {"name": "vip", "type": "boolean", "filled": 2},
            {"name": "x", "type": "empty", "filled": 0},
        ],
    }
    assert result_shape({"id": 1})["rows"] == 1
    assert result_shape("text") is None
    wide = result_shape([{f"c{i}": i for i in range(50)}], max_fields=5)
    assert [f["name"] for f in wide["fields"]] == ["c0", "c1", "c2", "c3", "c4"]


def test_json_kind_names_other_types():
    from datetime import date

    from elliot_core.redaction import _json_kind

    assert _json_kind(date(2026, 1, 1)) == "date"


def test_scrub_personal_text_removes_contact_details_and_long_numbers():
    from elliot_core.redaction import scrub_personal_text

    text = "Mail ada@example.co.uk or call +972 54-123-4567; card 4111 1111 1111 1111; got 12 rows"
    scrubbed = scrub_personal_text(text)
    assert (
        "ada@example.co.uk" not in scrubbed and "4111" not in scrubbed and "54-123" not in scrubbed
    )
    assert "‹email›" in scrubbed and scrubbed.count("‹number›") == 2
    assert "12 rows" in scrubbed
    assert scrub_personal_text("") == ""
