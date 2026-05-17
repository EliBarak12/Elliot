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

DNS-rebinding defense: :func:`validate_url` resolves the hostname and returns
the validated IPs. :func:`safe_request` (the one-shot helper) *pins* the
connection to one of those exact IPs via :class:`_PinnedTransport`, so httpx
cannot re-resolve the hostname to a different (now-malicious) address between
validation and connect. TLS is unaffected — SNI and certificate verification
still use the real hostname, only the connect-time address is overridden.

Callers that build their own client with :func:`safe_client` (e.g. paginated
fetchers that reuse one connection pool) opt into the same protection by
passing ``pinned_hosts`` built from :func:`validate_url`'s return value.
Without ``pinned_hosts`` the client still re-resolves at connect time, leaving
a small DNS-rebinding window between :func:`validate_url` and the request;
for those paths run behind an egress proxy that enforces the same allow-policy.
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


def validate_url(url: str, *, allow_private: bool | None = None) -> list[str]:
    """Validate an outbound URL. Raises :class:`SSRFError` if denied.

    Resolves the hostname via DNS once and rejects any non-public address
    unless ``allow_private`` (or the ``ELLIOT_SSRF_ALLOW_PRIVATE`` env var) is
    set.

    Args:
        url: Absolute URL to validate.
        allow_private: Override the env-var default. Pass ``True`` from
            trusted operator-controlled callsites (e.g. CLI probing the local
            plugin).

    Returns:
        The list of validated IP addresses the hostname resolved to. Callers
        that want DNS-rebinding protection pass one of these to
        :func:`safe_client` so the connection is pinned to a vetted address.
        If the URL host is already a literal IP, that IP is returned.
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
    validated: list[str] = []
    for _fam, _type, _proto, _canon, sockaddr in addrs:
        ip_str = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if not allow_private and _is_blocked_ip(ip):
            raise SSRFError(
                f"host '{host}' resolves to non-public address {ip_str}",
                url=url,
            )
        if ip_str not in validated:
            validated.append(ip_str)
    return validated


class _PinnedTransport(httpx.AsyncHTTPTransport):
    """Transport that pins connections to a pre-validated IP address.

    httpx (and the underlying httpcore connection pool) re-resolves the
    request hostname at connect time. That re-resolution is a DNS-rebinding
    window: the attacker domain that passed :func:`validate_url` can answer
    the second lookup with ``127.0.0.1`` or a metadata IP.

    This transport closes that window. For each request it rewrites the URL
    *host* to the validated IP (so the socket connects to the vetted address)
    while keeping the original hostname as the ``Host`` header and as the TLS
    SNI / certificate-verification name via httpx's ``sni_hostname`` extension.
    Cert validation is therefore unchanged — a connection to the pinned IP
    must still present a certificate valid for the real hostname.
    """

    def __init__(self, host_to_ip: dict[str, str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Keyed by lower-cased hostname.
        self._host_to_ip = {h.lower(): ip for h, ip in host_to_ip.items()}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        original_host = request.url.host
        pinned_ip = self._host_to_ip.get(original_host.lower())
        if pinned_ip is None:
            # No pin registered for this host (e.g. an un-validated redirect
            # target). Fail closed rather than connecting unvalidated.
            raise SSRFError(
                f"host '{original_host}' was not pre-validated for this client",
                url=str(request.url),
            )
        # Connect to the pinned IP; keep Host header + SNI on the real name.
        request.url = request.url.copy_with(host=pinned_ip)
        request.extensions = {**request.extensions, "sni_hostname": original_host}
        if "host" not in {k.lower() for k in request.headers}:
            request.headers["Host"] = original_host
        return await super().handle_async_request(request)


def safe_client(
    *,
    timeout: float = 30.0,
    follow_redirects: bool = False,
    headers: dict[str, str] | None = None,
    pinned_hosts: dict[str, str] | None = None,
) -> httpx.AsyncClient:
    """Return an :class:`httpx.AsyncClient` with SSRF-safe defaults.

    The caller MUST invoke :func:`validate_url` on the target URL before each
    request. When ``pinned_hosts`` is supplied (a ``{hostname: validated_ip}``
    map, e.g. built from :func:`validate_url`'s return value), the client uses
    a transport that connects only to those vetted IPs, closing the
    DNS-rebinding window. TLS SNI and cert verification still use the real
    hostname, so HTTPS is unaffected.

    Defaults:

    - ``follow_redirects=False`` — redirects must be inspected and re-validated.
    - ``timeout`` — total 30s; connect is capped at 5s.
    """
    connect_timeout = min(timeout, 5.0)
    transport: httpx.AsyncBaseTransport | None = None
    if pinned_hosts:
        transport = _PinnedTransport(pinned_hosts)
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=connect_timeout),
        follow_redirects=follow_redirects,
        headers=headers or {},
        transport=transport,
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

    Validates ``url``, then pins the connection to one of the IP addresses
    that validation vetted — so a DNS rebind between validation and connect
    cannot redirect the socket to a private/metadata address.

    Convenience for callsites that don't need to share a client/pool.
    """
    ips = validate_url(url, allow_private=allow_private)
    host = urlsplit(url).hostname or ""
    pinned_hosts = {host: ips[0]} if (host and ips) else None
    async with safe_client(
        timeout=timeout,
        follow_redirects=follow_redirects,
        pinned_hosts=pinned_hosts,
    ) as client:
        return await client.request(method, url, **kwargs)
