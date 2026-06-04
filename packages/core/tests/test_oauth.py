"""Tests for the shared OAuth 2.1 + PKCE client primitives."""

from __future__ import annotations

import base64
import hashlib

import pytest
import respx
from httpx import Response

from elliot_core.oauth import (
    build_authorize_url,
    exchange_code_for_tokens,
    generate_pkce,
    new_state,
    oauth_tls_verify,
    refresh_tokens,
)
from elliot_core.types import OAuth2Config


def _oauth2() -> OAuth2Config:
    return OAuth2Config(
        authorization_url="https://acme.com/oauth/authorize",
        token_url="https://acme.com/oauth/token",
        scopes=["read", "write"],
        client_id_secret="{{ env:ACME_CLIENT_ID }}",
        client_secret_secret="{{ env:ACME_CLIENT_SECRET }}",
    )


def test_generate_pkce_challenge_matches_verifier() -> None:
    verifier, challenge = generate_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    assert challenge == expected.decode().rstrip("=")
    assert "=" not in challenge


def test_new_state_is_unguessable_and_unique() -> None:
    assert new_state() != new_state()
    assert len(new_state()) >= 16


def test_build_authorize_url_includes_pkce_and_scope() -> None:
    url = build_authorize_url(
        _oauth2(),
        client_id="cid",
        redirect_uri="http://127.0.0.1:5000/callback",
        state="xyz",
        code_challenge="chal",
    )
    assert url.startswith("https://acme.com/oauth/authorize?")
    assert "response_type=code" in url
    assert "client_id=cid" in url
    assert "code_challenge=chal" in url
    assert "code_challenge_method=S256" in url
    assert "scope=read+write" in url
    assert "state=xyz" in url


def test_build_authorize_url_keeps_existing_query() -> None:
    oauth2 = _oauth2()
    oauth2.authorization_url = "https://acme.com/oauth/authorize?tenant=acme"
    url = build_authorize_url(
        oauth2,
        client_id="cid",
        redirect_uri="http://127.0.0.1/cb",
        state="s",
        code_challenge="c",
    )
    assert "?tenant=acme&" in url


def test_oauth_tls_verify_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELLIOT_OAUTH_INSECURE", raising=False)
    monkeypatch.delenv("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", raising=False)
    assert oauth_tls_verify() is True


def test_oauth_tls_verify_insecure_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELLIOT_OAUTH_INSECURE", "1")
    monkeypatch.delenv("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", raising=False)
    assert oauth_tls_verify() is False


def test_oauth_tls_verify_cloud_ignores_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELLIOT_OAUTH_INSECURE", "1")
    monkeypatch.setenv("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", "1")
    assert oauth_tls_verify() is True


@respx.mock
async def test_exchange_code_for_tokens_returns_payload() -> None:
    route = respx.post("https://acme.com/oauth/token").mock(
        return_value=Response(200, json={"access_token": "tok-123", "expires_in": 3600})
    )
    payload = await exchange_code_for_tokens(
        _oauth2(),
        client_id="cid",
        client_secret="csec",
        code="authcode",
        code_verifier="ver",
        redirect_uri="http://127.0.0.1/cb",
    )
    assert payload["access_token"] == "tok-123"
    assert route.called
    sent = route.calls.last.request
    assert b"grant_type=authorization_code" in sent.content
    assert b"code_verifier=ver" in sent.content


@respx.mock
async def test_refresh_tokens_uses_refresh_grant() -> None:
    route = respx.post("https://acme.com/oauth/token").mock(
        return_value=Response(200, json={"access_token": "tok-new"})
    )
    payload = await refresh_tokens(
        _oauth2(), refresh_token="rt", client_id="cid", client_secret="csec"
    )
    assert payload["access_token"] == "tok-new"
    assert b"grant_type=refresh_token" in route.calls.last.request.content
