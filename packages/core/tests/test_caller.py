"""Caller credentials: ``{{ caller:NAME }}`` placeholders bound per request."""

from __future__ import annotations

import asyncio

import pytest

from elliot_core.caller import (
    CallerCredentialMissingError,
    bound_caller,
    caller_credentials,
    caller_placeholder,
    mentions_caller,
    resolve_caller,
    source_uses_caller,
)
from elliot_core.linter import lint_connector
from elliot_core.sources.api_fetcher import _request_headers, _resolve_secret
from elliot_core.types import AuthConfig, ConnectorConfig, SourceConfig


def _source(**kw: object) -> SourceConfig:
    return SourceConfig(id="orders", name="Orders", type="rest", url="https://api.x/orders", **kw)


def test_placeholder_parsing() -> None:
    assert caller_placeholder("{{ caller:token }}") == "token"
    assert caller_placeholder("{{caller:sub}}") == "sub"
    assert caller_placeholder("Bearer {{ caller:token }}") is None
    assert caller_placeholder("{{ env:TOKEN }}") is None
    assert mentions_caller("Bearer {{ caller:token }}")
    assert not mentions_caller("{{ env:TOKEN }}")


def test_binding_is_scoped_and_reaches_child_tasks() -> None:
    async def scenario() -> tuple[str, str]:
        with caller_credentials({"sub": "user-1", "token": "t1", "email": ""}):
            inner = await asyncio.create_task(asyncio.sleep(0, resolve_caller("sub")))
            assert "email" not in (bound_caller() or {}), "empty values are not bound"
            return inner, resolve_caller("token")

    assert asyncio.run(scenario()) == ("user-1", "t1")
    assert bound_caller() is None
    with pytest.raises(CallerCredentialMissingError) as exc:
        resolve_caller("token")
    assert exc.value.code == "AUTH_REQUIRED"


def test_source_uses_caller_in_auth_or_headers() -> None:
    assert source_uses_caller(
        _source(auth=AuthConfig(type="bearer", secret_key="{{ caller:token }}"))
    )
    assert source_uses_caller(_source(headers={"X-User": "{{ caller:sub }}"}))
    assert not source_uses_caller(
        _source(auth=AuthConfig(type="bearer", secret_key="{{ env:TOKEN }}"))
    )


def test_design_time_uses_the_bound_caller_then_a_saved_test_value() -> None:
    src = _source(
        auth=AuthConfig(type="bearer", secret_key="{{ caller:token }}"),
        headers={"X-User": "{{ caller:sub }}"},
    )
    with caller_credentials({"token": "live", "sub": "u-9"}):
        assert _request_headers(src, {}) == {"X-User": "u-9", "Authorization": "Bearer live"}
    # Building, with test values saved as secrets.
    secrets = {"CALLER_TOKEN": "test-token", "CALLER_SUB": "test-user"}
    assert _request_headers(src, secrets) == {
        "X-User": "test-user",
        "Authorization": "Bearer test-token",
    }


def test_design_time_reads_an_exported_test_value_only_where_host_env_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CALLER_SUB", "env-user")
    assert _resolve_secret("{{ caller:sub }}", {}) == "env-user"
    monkeypatch.setenv("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", "1")
    with pytest.raises(CallerCredentialMissingError):
        _resolve_secret("{{ caller:sub }}", {})


def test_design_time_without_a_test_value_says_how_to_add_one() -> None:
    with pytest.raises(CallerCredentialMissingError, match="CALLER_TOKEN"):
        _resolve_secret("{{ caller:token }}", {})


def _codes(source: SourceConfig) -> set[str]:
    config = ConnectorConfig(name="C", slug="c", version="1.0.0", sources=[source], tools=[])
    return {i.code for i in lint_connector(config)}


def test_lint_accepts_a_caller_credential() -> None:
    codes = _codes(
        _source(
            auth=AuthConfig(type="bearer", secret_key="{{ caller:token }}"),
            headers={"X-User": "{{ caller:sub }}"},
        )
    )
    assert not codes & {"AUTH_LITERAL_SECRET", "CALLER_PLACEHOLDER_INVALID", "CALLER_NOT_REST"}


def test_lint_rejects_partial_or_unknown_caller_placeholders() -> None:
    assert "CALLER_PLACEHOLDER_INVALID" in _codes(
        _source(headers={"Authorization": "Bearer {{ caller:token }}"})
    )
    assert "CALLER_PLACEHOLDER_INVALID" in _codes(_source(headers={"X-Role": "{{ caller:role }}"}))


def test_lint_rejects_caller_credentials_on_a_database() -> None:
    src = SourceConfig(
        id="db",
        name="DB",
        type="postgres",
        url="{{ env:PG_URL }}",
        table="orders",
        headers={"X-User": "{{ caller:sub }}"},
    )
    assert "CALLER_NOT_REST" in _codes(src)
