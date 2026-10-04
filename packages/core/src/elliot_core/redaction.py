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
    # The authority with its userinfo removed, taken from ``netloc`` verbatim
    # rather than rebuilt from ``hostname`` and ``port``. Both of those were
    # wrong, in different ways, and this function is the one the whole repo
    # routes a URL through before it reaches a log, an error message or an API
    # payload.
    #
    # ``parts.port`` VALIDATES on access and raises outside the try above —
    # urlsplit is lazy, so the guard could never catch it — and the docstring
    # promises best-effort. Measured: "http://[::1]:notaport/x",
    # "http://host:99999999999999999999/x" and "http://host:-1/x" all raised
    # ValueError out of this function. It is reachable from an unauthenticated
    # request: routers/grader.py's public POST /api/grader/submissions calls
    # ``log.info("grader.submit", url=redact_url(url))`` as its first
    # statement, before the quota check and before anything looks at the URL —
    # measured against the running API, a posted "http://[::1]:notaport/mcp"
    # returned 500 Internal Server Error with that ValueError in the log. A
    # redactor that raises is worse than no redactor: it turns the log line
    # that was protecting the secret into the thing that fails.
    #
    # ``parts.hostname`` strips the brackets off an IPv6 literal, so
    # "http://[::1]:8000/mcp" came back as "http://::1:8000/mcp" — not a URL,
    # and ambiguous about where the address ends. Measured on three IPv6
    # forms; the loopback case is an everyday local MCP endpoint.
    #
    # Slicing at the LAST "@" because a password may contain one. This is
    # exactly what Elliot Cloud's redactUrl.ts already does — its header says
    # "this is a port of that function, and the two are meant to agree" — so
    # the two now agree on both shapes. One visible consequence: a host keeps
    # the case it was written in, where ``hostname`` lower-cased it. The mirror
    # has always done that, and this is a display helper, not a comparison.
    #
    # Differential-tested against that port over 30 URLs — DSNs, userinfo with
    # an "@" in the password, every sensitive query key, IPv6, bad ports,
    # fragments, a `{{ env:VAR }}` template: 29 agree exactly. The one that
    # does not is an upper-case SCHEME, which urlsplit lower-cases per RFC 3986
    # ("HTTPS://HOST/P" -> "https://HOST/P") and the port leaves alone. Left as
    # it is: the RFC behaviour is the right one and no defect sits behind it.
    netloc = parts.netloc
    at = netloc.rfind("@")
    if at != -1:
        netloc = netloc[at + 1 :]
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
