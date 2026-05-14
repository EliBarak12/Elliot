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

from typing import Any
from urllib.parse import urlsplit, urlunsplit

# Common secret-bearing parameter names (case-insensitive). Anything matching
# is replaced with the placeholder. The list is intentionally short — false
# negatives are better than mistakenly redacting non-secret fields like
# "key" in a key-value tool argument.
_SENSITIVE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "access_token",
        "accesstoken",
        "auth_token",
        "authtoken",
        "authorization",
        "bearer",
        "client_secret",
        "clientsecret",
        "password",
        "pwd",
        "secret",
        "secret_key",
        "secretkey",
        "session_token",
        "sessiontoken",
        "token",
        "x-api-key",
    }
)
_REDACTED = "***"
_MAX_VALUE_LEN = 256


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
            if k.lower() in _SENSITIVE_KEYS:
                out_parts.append(f"{k}={_REDACTED}")
            else:
                out_parts.append(pair)
        else:
            out_parts.append(pair)
    return "&".join(out_parts)


def redact_value(value: Any) -> Any:
    """Recursively redact obviously-sensitive values inside arbitrary data.

    Strings are returned as-is unless they're enormous (truncated). Dicts
    have any key matching ``_SENSITIVE_KEYS`` replaced with the placeholder.
    Lists are walked element-wise.
    """
    if isinstance(value, str):
        return value if len(value) <= _MAX_VALUE_LEN else value[:_MAX_VALUE_LEN] + "…[truncated]"
    if isinstance(value, dict):
        return {
            k: (
                _REDACTED
                if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS
                else redact_value(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_audit_arguments(arguments: Any) -> Any:
    """Public entry point for audit-log payload redaction."""
    return redact_value(arguments)
