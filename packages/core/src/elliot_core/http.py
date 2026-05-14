"""SSRF-hardened HTTP client wrapper for outbound calls to user-supplied URLs.

Use this module instead of constructing ``httpx.AsyncClient`` directly whenever
the destination URL is influenced by an agent, a connector author, or any
upstream service (e.g. ``rel="next"`` link headers, OpenAPI ``servers[].url``).

Defenses applied:

- **Scheme allowlist** — ``http`` and ``https`` only. Rejects ``file://``,
  ``gopher://``, ``ftp://``, ``data:``, …
- **Userinfo blocked** — ``user:pass@host`` is rejected so secrets cannot hide
  inside URLs and so a malicious upstream cannot inject credentials into the
  next-page link header.
- **DNS resolved once; non-public addresses rejected** — every resolved IP
  (v4 + v6) must be public. Private RFC1918, loopback, link-local
  (``169.254.169.254`` AWS / GCP metadata), multicast, reserved, and
  unspecified addresses are all blocked.
- **No redirect following by default** — callers must opt in and re-validate
  every redirect target.
- **Sensible timeouts** — connect timeout capped at 5s; total at 30s by
  default, configurable per call.

Opt-out: set ``ELLIOT_SSRF_ALLOW_PRIVATE=1`` for trusted internal deployments
that intentionally point connectors at intranet hosts. The default is strict.

Known limitation: DNS rebinding between validation and the actual TCP connect
is not fully mitigated, because ``httpx`` does not expose a resolver hook. The
window is small (microseconds), and an attacker who can rewrite DNS for your
host already has stronger primitives. For full pinning, run behind an egress
proxy that enforces the same allow-policy.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog

from elliot_core.errors import ElliotError

log = structlog.get_logger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
# Hostnames that should always be blocked when allow_private is False.
_BLOCKED_HOSTS = {
    "metadata.google.internal",
    "metadata",
    "instance-data",
}
# Cloud metadata IPs (covered by is_link_local for v4, but listed explicitly for v6 + clarity).
_BLOCKED_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}


class SSRFError(ElliotError):
    """Raised when an outbound URL violates the SSRF allow-policy."""

    def __init__(self, message: str, url: str | None = None) -> None:
        super().__init__("SSRF_BLOCKED", message)
        self.url = url


def _allow_private_env() -> bool:
    return os.environ.get("ELLIOT_SSRF_ALLOW_PRIVATE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip in _BLOCKED_IPS:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_url(url: str, *, allow_private: bool | None = None) -> None:
    """Validate an outbound URL. Raises :class:`SSRFError` if denied.

    Resolves the hostname via DNS once and rejects any non-public address
    unless ``allow_private`` (or the ``ELLIOT_SSRF_ALLOW_PRIVATE`` env var) is
    set.

    Args:
        url: Absolute URL to validate.
        allow_private: Override the env-var default. Pass ``True`` from
            trusted operator-controlled callsites (e.g. CLI probing the local
            plugin).
    """
    if allow_private is None:
        allow_private = _allow_private_env()
    if not url:
        raise SSRFError("URL is empty")
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise SSRFError(
            f"scheme '{parts.scheme}' not allowed; only http/https are permitted",
            url=url,
        )
    if parts.username or parts.password:
        raise SSRFError("URL must not include userinfo (user:pass@host)", url=url)
    host = parts.hostname
    if not host:
        raise SSRFError("URL is missing host", url=url)
    if not allow_private and host.lower() in _BLOCKED_HOSTS:
        raise SSRFError(f"host '{host}' is blocked (cloud metadata)", url=url)
    try:
        addrs = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SSRFError(f"DNS resolution failed for '{host}'", url=url) from exc
    for _fam, _type, _proto, _canon, sockaddr in addrs:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not allow_private and _is_blocked_ip(ip):
            raise SSRFError(
                f"host '{host}' resolves to non-public address {ip_str}",
                url=url,
            )


def safe_client(
    *,
    timeout: float = 30.0,
    follow_redirects: bool = False,
    headers: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    """Return an :class:`httpx.AsyncClient` with SSRF-safe defaults.

    The caller MUST invoke :func:`validate_url` on the target URL before each
    request. The client does not auto-validate because httpx does not expose
    a resolver hook; doing so here would be a footgun (callers would assume
    they're protected when they aren't, e.g. on redirects).

    Defaults:

    - ``follow_redirects=False`` — redirects must be inspected and re-validated.
    - ``timeout`` — total 30s; connect is capped at 5s.
    """
    connect_timeout = min(timeout, 5.0)
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
        follow_redirects=follow_redirects,
        headers=headers or {},
    )


async def safe_request(
    method: str,
    url: str,
    *,
    timeout: float = 30.0,
    follow_redirects: bool = False,
    allow_private: bool | None = None,
    **kwargs: Any,
) -> httpx.Response:
    """One-shot SSRF-safe request. Validates ``url`` then issues ``method``.

    Convenience for callsites that don't need to share a client/pool.
    """
    validate_url(url, allow_private=allow_private)
    async with safe_client(timeout=timeout, follow_redirects=follow_redirects) as client:
        return await client.request(method, url, **kwargs)
