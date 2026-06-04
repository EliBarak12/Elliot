"""Tests for the design-time loopback OAuth login used by discover."""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest
import respx
from httpx import Response

from elliot_core.types import OAuth2Config
from elliot_mcp_plugin.oauth_login import start_login


def _oauth2() -> OAuth2Config:
    return OAuth2Config(
        authorization_url="https://acme.example.com/oauth/authorize",
        token_url="https://acme.example.com/oauth/token",
        scopes=["read"],
        client_id_secret="{{ env:ACME_CLIENT_ID }}",
        client_secret_secret="{{ env:ACME_CLIENT_SECRET }}",
    )


def _hit_callback(port: int, query: str) -> int:
    # urllib (not httpx) so respx never intercepts the loopback request.
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?{query}", timeout=5) as resp:
        return int(resp.status)


def test_start_login_binds_loopback_and_builds_url() -> None:
    login = start_login(
        oauth2=_oauth2(), client_id="cid", client_secret="csec", name="acme", connect_id="c1"
    )
    try:
        assert login.port > 0
        assert login.redirect_uri == f"http://127.0.0.1:{login.port}/callback"
        # redirect_uri is percent-encoded inside the authorize URL.
        assert "callback" in login.authorize_url and str(login.port) in login.authorize_url
        assert "code_challenge_method=S256" in login.authorize_url
        assert f"state={login.state}" in login.authorize_url
    finally:
        login.shutdown()


@respx.mock
async def test_callback_then_exchange_returns_token() -> None:
    route = respx.post("https://acme.example.com/oauth/token").mock(
        return_value=Response(200, json={"access_token": "live-tok"})
    )
    login = start_login(
        oauth2=_oauth2(), client_id="cid", client_secret="csec", name="acme", connect_id="c1"
    )
    try:
        status = _hit_callback(login.port, f"code=authcode&state={login.state}")
        assert status == 200
        token = await login.wait_and_exchange(timeout=5)
        assert token == "live-tok"
        assert route.called
        # Repeat calls return the cached token without a second exchange.
        assert await login.wait_and_exchange(timeout=5) == "live-tok"
        assert route.call_count == 1
    finally:
        login.shutdown()


def test_callback_rejects_wrong_state() -> None:
    login = start_login(
        oauth2=_oauth2(), client_id="cid", client_secret="csec", name="acme", connect_id="c1"
    )
    try:
        with pytest.raises(urllib.error.HTTPError) as ei:
            _hit_callback(login.port, "code=x&state=not-the-state")
        assert ei.value.code == 400
        assert not login.event.is_set()
    finally:
        login.shutdown()


async def test_callback_error_param_raises() -> None:
    login = start_login(
        oauth2=_oauth2(), client_id="cid", client_secret="csec", name="acme", connect_id="c1"
    )
    try:
        with pytest.raises(urllib.error.HTTPError):
            _hit_callback(login.port, f"error=access_denied&state={login.state}")
        assert login.event.is_set()
        with pytest.raises(RuntimeError):
            await login.wait_and_exchange(timeout=5)
    finally:
        login.shutdown()


async def test_wait_times_out_when_no_callback() -> None:
    login = start_login(
        oauth2=_oauth2(), client_id="cid", client_secret="csec", name="acme", connect_id="c1"
    )
    try:
        with pytest.raises(TimeoutError):
            await login.wait_and_exchange(timeout=0.2)
    finally:
        login.shutdown()
