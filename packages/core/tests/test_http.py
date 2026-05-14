"""Tests for elliot_core.http SSRF defenses."""

from __future__ import annotations

import socket
from typing import Any
from unittest import mock

import pytest

from elliot_core.http import (
    SSRFError,
    safe_client,
    validate_url,
)

# ── scheme & userinfo ──────────────────────────────────────────────────────


def test_validate_url_rejects_empty():
    with pytest.raises(SSRFError, match="empty"):
        validate_url("")


def test_validate_url_rejects_file_scheme():
    with pytest.raises(SSRFError, match="scheme"):
        validate_url("file:///etc/passwd")


def test_validate_url_rejects_gopher_scheme():
    with pytest.raises(SSRFError, match="scheme"):
        validate_url("gopher://example.com/")


def test_validate_url_rejects_data_scheme():
    with pytest.raises(SSRFError, match="scheme"):
        validate_url("data:text/plain,hello")


def test_validate_url_rejects_userinfo():
    with pytest.raises(SSRFError, match="userinfo"):
        validate_url("http://user:pass@example.com/")


def test_validate_url_rejects_missing_host():
    with pytest.raises(SSRFError, match="host"):
        validate_url("http:///path")


# ── IP blocking via DNS ────────────────────────────────────────────────────


def _mock_getaddrinfo(*ips: str) -> Any:
    """Build a getaddrinfo side-effect that returns the given IPs."""

    def _inner(host: str, *args: Any, **kwargs: Any) -> list[tuple]:
        return [(socket.AF_INET, 0, 0, "", (ip, 0)) for ip in ips]

    return _inner


def test_validate_url_rejects_loopback_ip():
    with (
        mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("127.0.0.1")),
        pytest.raises(SSRFError, match="non-public"),
    ):
        validate_url("http://attacker.example.com/")


def test_validate_url_rejects_aws_metadata_ip():
    with (
        mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("169.254.169.254")),
        pytest.raises(SSRFError, match="non-public"),
    ):
        validate_url("http://attacker.example.com/")


def test_validate_url_rejects_rfc1918():
    for ip in ("10.0.0.1", "172.16.1.1", "192.168.1.1"):
        with (
            mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo(ip)),
            pytest.raises(SSRFError, match="non-public"),
        ):
            validate_url("http://attacker.example.com/")


def test_validate_url_rejects_gcp_metadata_hostname():
    # Pre-resolution name match — should fail before DNS even runs.
    with pytest.raises(SSRFError, match="cloud metadata"):
        validate_url("http://metadata.google.internal/computeMetadata/v1/")


def test_validate_url_accepts_public_ip():
    with mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("93.184.216.34")):
        validate_url("https://example.com/path")


def test_validate_url_rejects_when_any_ip_is_private():
    # IPv4 + IPv6 — if either is private, reject.
    with (
        mock.patch(
            "socket.getaddrinfo",
            side_effect=_mock_getaddrinfo("93.184.216.34", "127.0.0.1"),
        ),
        pytest.raises(SSRFError, match="non-public"),
    ):
        validate_url("http://attacker.example.com/")


def test_validate_url_dns_failure_blocked():
    def _gaierror(*_a: Any, **_kw: Any) -> Any:
        raise socket.gaierror("no such host")

    with (
        mock.patch("socket.getaddrinfo", side_effect=_gaierror),
        pytest.raises(SSRFError, match="DNS"),
    ):
        validate_url("http://does-not-resolve.example.invalid/")


# ── allow_private opt-in ───────────────────────────────────────────────────


def test_validate_url_allow_private_kwarg():
    with mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("127.0.0.1")):
        validate_url("http://internal.example.com/", allow_private=True)


def test_validate_url_allow_private_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ELLIOT_SSRF_ALLOW_PRIVATE", "1")
    with mock.patch("socket.getaddrinfo", side_effect=_mock_getaddrinfo("10.0.0.1")):
        validate_url("http://internal.example.com/")


# ── safe_client defaults ───────────────────────────────────────────────────


def test_safe_client_default_no_redirects():
    client = safe_client()
    try:
        assert client.follow_redirects is False
    finally:
        # AsyncClient must be closed via aclose(); for the sync default test
        # we drop the reference and rely on GC. (Tested for attribute only.)
        pass


def test_safe_client_explicit_follow_redirects():
    client = safe_client(follow_redirects=True)
    try:
        assert client.follow_redirects is True
    finally:
        pass
