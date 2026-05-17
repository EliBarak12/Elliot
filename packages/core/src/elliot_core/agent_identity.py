"""Structured agent identity captured from request headers.

Implements the Agent Experience (AX) "Transparent Identity" / "Differentiate
Agent Interaction" principles: every request that reaches an Elliot service
carries enough information for observability to attribute the call to a
specific agent client and model, not just a generic 'mcp' bucket.

The recognised wire format follows the AX User-Agent convention:

    agent-<tool>[/<version>]  [model-<model-id>]  [modality-<modality>]

Examples:

    agent-claude-code/1.42.0 claude-opus-4-7 modality-plaintext
    agent-cursor/0.45 model-claude-sonnet-4-5
    agent-codex

Common MCP client UA strings (Claude Code, Cursor, Codex, Windsurf, VS Code)
are also recognised as a fallback. The legacy ``x-client-name`` header used by
Studio is honoured when nothing else is available.
"""

from __future__ import annotations

import contextvars
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

__all__ = [
    "AgentIdentity",
    "parse_agent_identity",
    "merge_client_info",
    "get_current_agent_identity",
    "set_current_agent_identity",
    "reset_current_agent_identity",
]


@dataclass(frozen=True)
class AgentIdentity:
    """Structured identity for an agent making a request to Elliot."""

    client: str | None = None
    client_version: str | None = None
    model: str | None = None
    modality: str | None = None
    user_agent: str | None = None

    def display(self) -> str:
        """One-line label for logs and the legacy ``agent_hint`` column."""
        parts = []
        if self.client:
            label = self.client
            if self.client_version:
                label = f"{label}/{self.client_version}"
            parts.append(label)
        if self.model:
            parts.append(self.model)
        if parts:
            return " ".join(parts)
        if self.user_agent:
            return self.user_agent
        return "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "client": self.client,
            "client_version": self.client_version,
            "model": self.model,
            "modality": self.modality,
            "user_agent": self.user_agent,
        }


_AX_AGENT_RE = re.compile(r"agent-([A-Za-z0-9_.-]+)(?:/([A-Za-z0-9_.+-]+))?", re.IGNORECASE)
_AX_MODEL_RE = re.compile(r"\bmodel-([A-Za-z0-9_.-]+)", re.IGNORECASE)
_AX_MODALITY_RE = re.compile(r"\bmodality-([A-Za-z0-9_.-]+)", re.IGNORECASE)
_BARE_MODEL_RE = re.compile(
    r"\b(claude-[A-Za-z0-9_.-]+|gpt-[A-Za-z0-9_.-]+|o[0-9][A-Za-z0-9_.-]*|gemini-[A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_KNOWN_CLIENTS = (
    "claude-code",
    "cursor",
    "codex",
    "windsurf",
    "continue",
    "cline",
    "zed",
    "vscode",
)


def parse_agent_identity(headers: Mapping[str, str]) -> AgentIdentity:
    """Parse User-Agent and ``x-client-name`` into a structured identity.

    The ``headers`` mapping is expected to be lowercase-keyed. Returns an
    :class:`AgentIdentity` whose fields may all be ``None`` when nothing is
    recognisable — callers should treat that as an unknown agent rather than
    an error.
    """
    user_agent = headers.get("user-agent") or None
    explicit_client = headers.get("x-client-name") or None

    client: str | None = None
    client_version: str | None = None
    model: str | None = None
    modality: str | None = None

    if user_agent:
        ax = _AX_AGENT_RE.search(user_agent)
        if ax:
            client = ax.group(1).lower()
            client_version = ax.group(2)
        else:
            for name in _KNOWN_CLIENTS:
                m = re.search(
                    rf"\b{re.escape(name)}(?:[\s/-]([A-Za-z0-9_.+-]+))?", user_agent, re.I
                )
                if m:
                    client = name
                    client_version = m.group(1)
                    break

        mm = _AX_MODEL_RE.search(user_agent)
        if mm:
            model = mm.group(1).lower()
        else:
            mm = _BARE_MODEL_RE.search(user_agent)
            if mm:
                model = mm.group(1).lower()

        md = _AX_MODALITY_RE.search(user_agent)
        if md:
            modality = md.group(1).lower()

    if not client and explicit_client:
        client = explicit_client.lower()

    return AgentIdentity(
        client=client,
        client_version=client_version,
        model=model,
        modality=modality,
        user_agent=user_agent,
    )


def merge_client_info(
    identity: AgentIdentity | None,
    client_name: str | None,
    client_version: str | None = None,
) -> AgentIdentity:
    """Overlay an MCP ``initialize`` clientInfo onto a header-parsed identity.

    The MCP handshake's ``clientInfo`` is the most reliable signal of which
    harness is connected (Claude Code, Cursor, Codex, ...), so it takes
    precedence over the User-Agent parse for the ``client`` field. Model and
    modality — which MCP does not carry — are preserved from the header parse.
    """
    base = identity or AgentIdentity()
    if not client_name or not client_name.strip():
        return base
    return replace(
        base,
        client=client_name.strip().lower(),
        client_version=client_version or base.client_version,
    )


_agent_identity_var: contextvars.ContextVar[AgentIdentity | None] = contextvars.ContextVar(
    "elliot_agent_identity", default=None
)


def get_current_agent_identity() -> AgentIdentity | None:
    """Return the identity attached to the current request, if any."""
    return _agent_identity_var.get()


def set_current_agent_identity(
    identity: AgentIdentity | None,
) -> contextvars.Token[AgentIdentity | None]:
    """Bind ``identity`` to the current async context. Returns the reset token."""
    return _agent_identity_var.set(identity)


def reset_current_agent_identity(token: contextvars.Token[AgentIdentity | None]) -> None:
    """Restore the previous identity binding using the token from ``set``."""
    _agent_identity_var.reset(token)
