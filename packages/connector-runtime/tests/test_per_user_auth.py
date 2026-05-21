"""Tests for per-user connector auth: vault, OAuth flow, executor pool."""

from __future__ import annotations

import time

import pytest

from elliot_connector_runtime.credential_resolver import ExecutorPool
from elliot_connector_runtime.executor import _build_auth_headers
from elliot_connector_runtime.oauth_flow import (
    build_authorize_url,
    generate_pkce,
)
from elliot_connector_runtime.oauth_store import CredentialVault, StoredCredential
from elliot_core.errors import ElliotError
from elliot_core.types import (
    AuthConfig,
    ConnectorConfig,
    OAuth2Config,
    SourceConfig,
)


def _oauth_source() -> SourceConfig:
    return SourceConfig(
        id="mail",
        name="MailBox",
        type="rest",
        url="https://api.example.com/messages",
        auth=AuthConfig(
            type="oauth2",
            scope="per_user",
            secret_key="access_token",
            oauth2=OAuth2Config(
                authorization_url="https://auth.example.com/authorize",
                token_url="https://auth.example.com/token",
                scopes=["mail.read"],
                client_id_secret="{{ env:CID }}",
                client_secret_secret="{{ env:CSECRET }}",
            ),
        ),
    )


def _connector(source: SourceConfig) -> ConnectorConfig:
    return ConnectorConfig(
        name="MailBox", slug="mailbox", version="1.0.0", sources=[source], tools=[]
    )


# ── vault ────────────────────────────────────────────────────────────────────


def test_vault_roundtrip_encrypts_and_returns() -> None:
    vault = CredentialVault(":memory:")
    vault.put(
        StoredCredential(
            user_id="u1", connector="mailbox", source_id="mail", kind="oauth2", secret="tok-abc"
        )
    )
    got = vault.get("u1", "mailbox", "mail")
    assert got is not None
    assert got.secret == "tok-abc"
    assert got.kind == "oauth2"


def test_vault_isolates_users() -> None:
    vault = CredentialVault(":memory:")
    vault.put(StoredCredential("u1", "mailbox", "mail", "api_key", "key-1"))
    vault.put(StoredCredential("u2", "mailbox", "mail", "api_key", "key-2"))
    assert vault.get("u1", "mailbox", "mail").secret == "key-1"  # type: ignore[union-attr]
    assert vault.get("u2", "mailbox", "mail").secret == "key-2"  # type: ignore[union-attr]
    assert vault.get("u3", "mailbox", "mail") is None


def test_stored_credential_expiry() -> None:
    assert StoredCredential("u", "c", "s", "oauth2", "t", expires_at=None).is_expired() is False
    assert (
        StoredCredential("u", "c", "s", "oauth2", "t", expires_at=time.time() - 5).is_expired()
        is True
    )
    assert (
        StoredCredential("u", "c", "s", "oauth2", "t", expires_at=time.time() + 3600).is_expired()
        is False
    )


# ── oauth flow helpers ─────────────────────────────────────────────────────────


def test_generate_pkce_distinct() -> None:
    v1, c1 = generate_pkce()
    v2, c2 = generate_pkce()
    assert v1 != v2 and c1 != c2
    assert len(c1) > 20


def test_build_authorize_url_has_pkce_and_resource() -> None:
    src = _oauth_source()
    assert src.auth is not None and src.auth.oauth2 is not None
    url = build_authorize_url(
        src.auth.oauth2,
        client_id="cid-123",
        redirect_uri="http://localhost:3001/oauth/callback/mail",
        state="st",
        code_challenge="chal",
    )
    assert "response_type=code" in url
    assert "code_challenge=chal" in url
    assert "code_challenge_method=S256" in url
    assert "client_id=cid-123" in url
    assert "scope=mail.read" in url


# ── auth header injection ──────────────────────────────────────────────────────


def test_build_auth_headers_oauth2_is_bearer() -> None:
    auth = AuthConfig(type="oauth2", scope="per_user", secret_key="access_token")
    headers = _build_auth_headers(auth, {"access_token": "live-token"})
    assert headers == {"Authorization": "Bearer live-token"}


# ── executor pool ──────────────────────────────────────────────────────────────


def test_pool_shared_connector_ignores_user() -> None:
    """A connector with no per_user source returns one shared executor."""
    captured: list[dict[str, str]] = []

    def factory(config: ConnectorConfig, secrets: dict[str, str]) -> object:  # type: ignore[return-value]
        captured.append(secrets)
        return object()

    src = SourceConfig(id="s", name="S", type="rest", url="https://x")
    pool = ExecutorPool(_connector(src), {"k": "v"}, vault=None, executor_factory=factory)  # type: ignore[arg-type]
    assert pool.requires_user_auth is False


@pytest.mark.asyncio
async def test_pool_per_user_missing_credential_raises_auth_required() -> None:
    vault = CredentialVault(":memory:")
    pool = ExecutorPool(_connector(_oauth_source()), {"CID": "c", "CSECRET": "s"}, vault=vault)
    assert pool.requires_user_auth is True
    with pytest.raises(ElliotError) as ei:
        await pool.get_executor("alice")
    assert ei.value.code == "AUTH_REQUIRED"
    connect = ei.value.detail["connect"]
    assert connect[0]["source_id"] == "mail"
    assert "/oauth/start/mail?user=alice" in connect[0]["connect_url"]


@pytest.mark.asyncio
async def test_pool_no_user_identity_raises() -> None:
    pool = ExecutorPool(_connector(_oauth_source()), {}, vault=CredentialVault(":memory:"))
    with pytest.raises(ElliotError) as ei:
        await pool.get_executor(None)
    assert ei.value.code == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_pool_injects_per_user_token_into_executor_secrets() -> None:
    vault = CredentialVault(":memory:")
    vault.put(StoredCredential("alice", "mailbox", "mail", "oauth2", "alice-token"))
    vault.put(StoredCredential("bob", "mailbox", "mail", "oauth2", "bob-token"))

    captured: dict[str, dict[str, str]] = {}

    def factory(config: ConnectorConfig, secrets: dict[str, str]) -> object:  # type: ignore[return-value]
        # remember which token this executor was built with
        captured[secrets["access_token"]] = secrets
        return object()

    pool = ExecutorPool(
        _connector(_oauth_source()),
        {"CID": "c", "CSECRET": "s"},
        vault=vault,
        executor_factory=factory,  # type: ignore[arg-type]
    )
    await pool.get_executor("alice")
    await pool.get_executor("bob")
    assert "alice-token" in captured
    assert "bob-token" in captured
