"""Redaction helpers for log lines and error messages.

CLAUDE.md mandates that secrets never appear in logs and that error messages
returned to agents do not leak server internals. This module is the single
place we strip:

- userinfo from URLs (``https://user:pass@host`` → ``https://host``)
- known-sensitive query params (``?api_key=`` etc.)
- "looks-like-a-secret" values from arbitrary dicts when writing audit /
  session NDJSON

Use ``redact_url`` whenever a URL is about to land in an error message or
log line. Use ``redact_audit_arguments`` whenever you serialize a raw
``arguments`` dict for an audit / observability sink.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Exact secret-bearing parameter names (case-insensitive). Matched in full.
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api_token",
        "x-api-key",
        "x-api-token",
        "access_token",
        "accesstoken",
        "refresh_token",
        "refreshtoken",
        "auth_token",
        "authtoken",
        "authorization",
        "bearer",
        "client_secret",
        "clientsecret",
        "client_id",
        "password",
        "passwd",
        "pwd",
        "db_password",
        "database_password",
        "secret",
        "secret_key",
        "secretkey",
        "session_token",
        "sessiontoken",
        "token",
        "private_key",
        "privatekey",
        "credential",
        "credentials",
        "cookie",
        "set-cookie",
    }
)
# Substrings: any key CONTAINING one of these (case-insensitive) is redacted.
# This catches naming variants like ``stripe_secret``, ``user_password``,
# ``oauth_access_token``, ``x-api-token`` without enumerating every name.
_SENSITIVE_SUBSTRINGS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "auth",
    "private_key",
    "privatekey",
)
_REDACTED = "***"
_MAX_VALUE_LEN = 256

# High-confidence secret-shaped value patterns. These catch a secret that
# slipped in under a benign key name (e.g. {"note": "Bearer sk-live-..."}),
# which pure key-name matching misses. Kept conservative to avoid redacting
# legitimate data.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),  # JWT
    re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test)[-_][A-Za-z0-9]{8,}"),  # Stripe-style
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),  # OpenAI-style
    re.compile(r"\bgh[posru]_[A-Za-z0-9]{20,}"),  # GitHub token
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack token
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM private key
)


def _value_looks_secret(value: str) -> bool:
    """True if a string value matches a known secret token pattern."""
    return any(p.search(value) for p in _SECRET_VALUE_PATTERNS)


def _is_sensitive_key(key: Any) -> bool:
    """Return True if ``key`` names a secret-bearing field.

    Matching is case-insensitive: exact membership in ``_SENSITIVE_KEYS`` or a
    substring hit against ``_SENSITIVE_SUBSTRINGS``.
    """
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if lowered in _SENSITIVE_KEYS:
        return True
    return any(sub in lowered for sub in _SENSITIVE_SUBSTRINGS)


def redact_url(url: str | None) -> str:
    """Return ``url`` with userinfo and known secret-y query params removed.

    Best-effort: bare query strings like ``?token=abc&other=ok`` are
    rewritten to ``?token=***&other=ok``. Returns the input unchanged on
    parse failure.
    """
    if not url:
        return url or ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return _REDACTED
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    new_query = _redact_query(parts.query) if parts.query else ""
    return urlunsplit((parts.scheme, netloc, parts.path, new_query, parts.fragment))


def _redact_query(qs: str) -> str:
    out_parts: list[str] = []
    for pair in qs.split("&"):
        if "=" in pair:
            k, _, v = pair.partition("=")
            if _is_sensitive_key(k):
                out_parts.append(f"{k}={_REDACTED}")
            else:
                out_parts.append(pair)
        else:
            out_parts.append(pair)
    return "&".join(out_parts)


def redact_value(value: Any) -> Any:
    """Recursively redact obviously-sensitive values inside arbitrary data.

    Strings matching a known secret-token pattern are replaced; otherwise
    they're returned as-is unless enormous (truncated). Dicts have any key
    matching ``_SENSITIVE_KEYS`` replaced with the placeholder. Lists are
    walked element-wise.
    """
    if isinstance(value, str):
        if _value_looks_secret(value):
            return _REDACTED
        return value if len(value) <= _MAX_VALUE_LEN else value[:_MAX_VALUE_LEN] + "…[truncated]"
    if isinstance(value, dict):
        return {
            k: (_REDACTED if _is_sensitive_key(k) else redact_value(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_audit_arguments(arguments: Any) -> Any:
    """Public entry point for audit-log payload redaction."""
    return redact_value(arguments)


def describe_value(value: Any) -> str:
    """What a value is, without what it says: ``‹text · 12 chars›``.

    Observability shows connector owners *how* agents used a tool, never the
    private data their end users typed or got back.
    """
    if isinstance(value, bool):
        return "‹true›" if value else "‹false›"
    if isinstance(value, str):
        return f"‹text · {len(value)} chars›"
    if isinstance(value, int | float):
        return "‹number›"
    if isinstance(value, dict):
        return f"‹object · {len(value)} keys›"
    if isinstance(value, list | tuple):
        return f"‹list · {len(value)} items›"
    if value is None:
        return "‹empty›"
    return f"‹{type(value).__name__}›"


def mask_call_arguments(arguments: Any, keep: frozenset[str] | set[str] = frozenset()) -> Any:
    """Agent arguments as an owner may see them.

    An argument keeps its value only when the value cannot identify a person:
    a key named in ``keep`` (the tool's closed value sets — enums the author
    defined — and flags such as ``confirm``), a boolean, or a number used as a
    bound or a count. Free text, dates, objects and lists are replaced by
    :func:`describe_value`. Secret-bearing keys are masked as before.
    """
    if not isinstance(arguments, dict):
        return arguments
    out: dict[str, Any] = {}
    for key, value in redact_value(arguments).items():
        # Booleans and numbers (bounds, counts, ids) are kept; bool is an int.
        if value == _REDACTED or key in keep or value is None or isinstance(value, int | float):
            out[key] = value
        else:
            out[key] = describe_value(value)
    return out


def result_shape(rows: Any, *, max_fields: int = 40) -> dict[str, Any] | None:
    """The metadata of a tool result — never its values.

    ``{"rows": 12, "fields": [{"name": "title", "type": "text", "filled": 12},
    …]}``: how many rows came back, which fields they carried, each field's
    JSON type, and in how many rows it had a value. Enough to see that a tool
    answered, how much, and whether a field the agent needed was empty — and
    nothing a person could be identified from.
    """
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return None
    fields: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            entry = fields.get(key)
            if entry is None:
                if len(fields) >= max_fields:
                    continue
                entry = fields[key] = {"name": str(key), "type": None, "filled": 0}
            if value is None or value == "" or value == [] or value == {}:
                continue
            entry["filled"] += 1
            kind = _json_kind(value)
            if entry["type"] is None:
                entry["type"] = kind
            elif entry["type"] != kind:
                entry["type"] = "mixed"
    return {
        "rows": len(rows),
        "fields": [{**f, "type": f["type"] or "empty"} for f in fields.values()],
    }


def _json_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list | tuple):
        return "list"
    return type(value).__name__


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 9+ digits, optionally separated by spaces, dots or dashes: phone numbers,
# card and account numbers, national ids. Short numbers (prices, counts, ids
# like 150) are left alone.
_LONG_NUMBER = re.compile(r"\+?\d(?:[\s.\-()]*\d){8,}")


def scrub_personal_text(text: str) -> str:
    """Remove contact details and long identifying numbers from free text.

    For text an agent writes about a call (feedback summaries) that an owner
    will read: the agent is told not to include personal data, and this
    catches the common slips — an email address, a phone or card number.
    """
    if not text:
        return text
    text = _EMAIL.sub("‹email›", text)
    return _LONG_NUMBER.sub("‹number›", text)
