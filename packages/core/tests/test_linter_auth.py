"""Linter guardrails for per-user / OAuth connector auth."""

from __future__ import annotations

from elliot_core.linter import lint_connector
from elliot_core.types import AuthConfig, ConnectorConfig, OAuth2Config, SourceConfig


def _connector(source: SourceConfig) -> ConnectorConfig:
    return ConnectorConfig(name="C", slug="c", version="1.0.0", sources=[source], tools=[])


def _codes(source: SourceConfig) -> set[str]:
    return {i.code for i in lint_connector(_connector(source))}


def test_oauth2_without_config_block_is_error() -> None:
    src = SourceConfig(
        id="s",
        name="S",
        type="rest",
        url="https://x",
        auth=AuthConfig(type="oauth2", secret_key="t"),
    )
    issues = lint_connector(_connector(src))
    err = [i for i in issues if i.code == "AUTH_OAUTH2_MISSING_CONFIG"]
    assert err and err[0].severity == "ERROR"


def test_literal_secret_in_shared_auth_warns() -> None:
    src = SourceConfig(
        id="s",
        name="S",
        type="rest",
        url="https://x",
        auth=AuthConfig(type="api_key", header_name="X-Key", secret_key="sk-live-hardcoded-123"),
    )
    assert "AUTH_LITERAL_SECRET" in _codes(src)


def test_env_placeholder_secret_is_clean() -> None:
    src = SourceConfig(
        id="s",
        name="S",
        type="rest",
        url="https://x",
        auth=AuthConfig(type="api_key", header_name="X-Key", secret_key="{{ env:API_KEY }}"),
    )
    assert "AUTH_LITERAL_SECRET" not in _codes(src)


def test_oauth2_client_creds_must_be_env() -> None:
    src = SourceConfig(
        id="s",
        name="S",
        type="rest",
        url="https://x",
        auth=AuthConfig(
            type="oauth2",
            scope="per_user",
            secret_key="access_token",
            oauth2=OAuth2Config(
                authorization_url="https://a/authorize",
                token_url="https://a/token",
                client_id_secret="literal-client-id",
                client_secret_secret="{{ env:CSECRET }}",
            ),
        ),
    )
    assert "AUTH_OAUTH2_CLIENT_NOT_ENV" in _codes(src)


def test_valid_per_user_oauth2_connector_is_clean() -> None:
    src = SourceConfig(
        id="s",
        name="S",
        type="rest",
        url="https://x",
        auth=AuthConfig(
            type="oauth2",
            scope="per_user",
            secret_key="access_token",
            oauth2=OAuth2Config(
                authorization_url="https://a/authorize",
                token_url="https://a/token",
                scopes=["read"],
                client_id_secret="{{ env:CID }}",
                client_secret_secret="{{ env:CSECRET }}",
            ),
        ),
    )
    codes = _codes(src)
    assert "AUTH_OAUTH2_MISSING_CONFIG" not in codes
    assert "AUTH_LITERAL_SECRET" not in codes
    assert "AUTH_OAUTH2_CLIENT_NOT_ENV" not in codes
    assert "AUTH_PER_USER_SLOT_IS_ENV" not in codes
