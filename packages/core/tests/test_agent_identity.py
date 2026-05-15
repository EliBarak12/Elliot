"""Tests for elliot_core.agent_identity."""

from __future__ import annotations

from elliot_core.agent_identity import (
    AgentIdentity,
    get_current_agent_identity,
    parse_agent_identity,
    reset_current_agent_identity,
    set_current_agent_identity,
)


def test_parse_ax_user_agent_full() -> None:
    headers = {
        "user-agent": "agent-claude-code/1.42.0 model-claude-opus-4-7 modality-plaintext",
    }
    identity = parse_agent_identity(headers)
    assert identity.client == "claude-code"
    assert identity.client_version == "1.42.0"
    assert identity.model == "claude-opus-4-7"
    assert identity.modality == "plaintext"


def test_parse_ax_user_agent_minimal() -> None:
    headers = {"user-agent": "agent-cursor"}
    identity = parse_agent_identity(headers)
    assert identity.client == "cursor"
    assert identity.client_version is None
    assert identity.model is None


def test_parse_recognises_known_client_without_ax_prefix() -> None:
    headers = {"user-agent": "Cursor/0.45.1 (macOS) claude-sonnet-4-5"}
    identity = parse_agent_identity(headers)
    assert identity.client == "cursor"
    assert identity.client_version == "0.45.1"
    assert identity.model == "claude-sonnet-4-5"


def test_parse_falls_back_to_x_client_name() -> None:
    headers = {"user-agent": "curl/8.1.2", "x-client-name": "elliot-studio"}
    identity = parse_agent_identity(headers)
    assert identity.client == "elliot-studio"
    assert identity.user_agent == "curl/8.1.2"


def test_parse_returns_empty_for_unknown_ua() -> None:
    headers = {"user-agent": "Mozilla/5.0 random browser"}
    identity = parse_agent_identity(headers)
    assert identity.client is None
    assert identity.model is None
    assert identity.user_agent == "Mozilla/5.0 random browser"


def test_parse_handles_missing_headers() -> None:
    identity = parse_agent_identity({})
    assert identity == AgentIdentity()
    assert identity.display() == "unknown"


def test_display_prefers_client_and_model() -> None:
    identity = AgentIdentity(client="codex", client_version="0.3", model="gpt-5")
    assert identity.display() == "codex/0.3 gpt-5"


def test_to_dict_round_trip() -> None:
    identity = AgentIdentity(
        client="claude-code",
        client_version="1.0",
        model="claude-opus-4-7",
        modality="plaintext",
        user_agent="agent-claude-code/1.0 claude-opus-4-7 modality-plaintext",
    )
    payload = identity.to_dict()
    assert payload["client"] == "claude-code"
    assert payload["model"] == "claude-opus-4-7"
    assert payload["modality"] == "plaintext"


def test_contextvar_set_get_reset() -> None:
    assert get_current_agent_identity() is None
    identity = AgentIdentity(client="cursor", model="claude-sonnet-4-5")
    token = set_current_agent_identity(identity)
    try:
        current = get_current_agent_identity()
        assert current is not None
        assert current.client == "cursor"
    finally:
        reset_current_agent_identity(token)
    assert get_current_agent_identity() is None
