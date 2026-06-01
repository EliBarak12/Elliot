"""Secret resolution and the multi-tenant host-environment gate.

``_resolve_secret`` resolves a connector's ``auth.secret_key`` to a concrete
value. In single-user Elliot a ``{{ env:NAME }}`` template may fall back to the
host process environment. In the multi-tenant cloud that fallback is a
cross-tenant exfiltration primitive, so it is disabled via
``ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS=1``.
"""

from __future__ import annotations

import pytest

from elliot_connector_runtime.executor import _resolve_secret


@pytest.fixture(autouse=True)
def _clear_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Default each test to the single-user (gate-off) posture unless it opts in.
    monkeypatch.delenv("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", raising=False)


def test_secret_dict_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEWS_TOKEN", "from-host-env")
    assert _resolve_secret("{{ env:REVIEWS_TOKEN }}", {"REVIEWS_TOKEN": "from-map"}) == "from-map"


def test_single_user_falls_back_to_host_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gate off (default): the host environment is the secret store.
    monkeypatch.setenv("REVIEWS_TOKEN", "from-host-env")
    assert _resolve_secret("{{ env:REVIEWS_TOKEN }}", {}) == "from-host-env"


def test_cloud_gate_blocks_host_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gate on (cloud): a tenant connector must NOT read the server's env, even
    # for sensitive platform variables it might try to name.
    monkeypatch.setenv("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", "1")
    monkeypatch.setenv("ELLIOT_CLOUD_SECRETS_ENCRYPTION_KEY", "super-secret-fernet-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    assert _resolve_secret("{{ env:ELLIOT_CLOUD_SECRETS_ENCRYPTION_KEY }}", {}) == ""
    assert _resolve_secret("{{ env:AWS_SECRET_ACCESS_KEY }}", {}) == ""


def test_cloud_gate_still_resolves_from_tenant_map(monkeypatch: pytest.MonkeyPatch) -> None:
    # The closed map (this tenant's resolved secrets) still works with the gate on.
    monkeypatch.setenv("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", "1")
    monkeypatch.setenv("REVIEWS_TOKEN", "from-host-env")
    assert _resolve_secret("{{ env:REVIEWS_TOKEN }}", {"REVIEWS_TOKEN": "tenant-value"}) == (
        "tenant-value"
    )


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes", "on"])
def test_gate_truthy_values(monkeypatch: pytest.MonkeyPatch, flag: str) -> None:
    monkeypatch.setenv("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", flag)
    monkeypatch.setenv("SOME_TOKEN", "host-value")
    assert _resolve_secret("{{ env:SOME_TOKEN }}", {}) == ""


def test_resolved_literal_passthrough() -> None:
    # Case 3: a non-template, non-dict key is already the resolved literal.
    assert _resolve_secret("literal-token-value", {}) == "literal-token-value"
