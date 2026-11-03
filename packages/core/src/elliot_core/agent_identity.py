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
    "principal_from_headers",
    "recall_client",
    "remember_client",
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
    # From the MCP ``initialize`` handshake (not headers): the spec version the
    # client speaks, and the capability names it advertised (roots, sampling,
    # elicitation, …). These are spec-backed — unlike ``model``, which MCP does
    # not carry, so it must be volunteered by the client (X-Model header / UA).
    protocol_version: str | None = None
    capabilities: tuple[str, ...] | None = None
    # A pseudonymous id for WHO is calling — a short hash of the signed-in
    # end user (or of the connector key / bearer token when there is no
    # user). Never reversible to the person. It keeps two people's calls
    # from being stitched into one "session" just because they use the same
    # client, and lets a client name learned at initialize follow the same
    # caller's later stateless calls.
    principal: str | None = None

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
            "protocol_version": self.protocol_version,
            "capabilities": list(self.capabilities) if self.capabilities is not None else None,
            "principal": self.principal,
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
    # MCP carries no model field, so a client that wants its model attributed
    # volunteers it in an explicit header. This is the reliable channel; the
    # User-Agent parse below is a best-effort fallback.
    explicit_model = headers.get("x-model") or headers.get("x-model-name") or None
    explicit_modality = headers.get("x-modality") or None

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
    # An explicit header wins over the UA heuristic for model/modality.
    if explicit_model:
        model = explicit_model.lower()
    if explicit_modality:
        modality = explicit_modality.lower()

    return AgentIdentity(
        client=client,
        client_version=client_version,
        model=model,
        modality=modality,
        user_agent=user_agent,
        principal=principal_from_headers(headers),
    )


def _digest(value: str) -> str:
    import hashlib

    return "p_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def principal_from_headers(headers: Mapping[str, str]) -> str | None:
    """A pseudonymous caller id: the end user if known, else the credential.

    The signed-in Elliot user (``x-elliot-user``, set by the gateway after it
    verified the token) is the most stable; a connector key or bearer token
    stands in when there is no user. Only a truncated SHA-256 is kept.
    """
    for name in ("x-elliot-user", "x-elliot-key", "authorization"):
        value = (headers.get(name) or "").strip()
        if value:
            return _digest(f"{name}:{value}")
    return None


# Client names learned from ``initialize``, for the stateless calls after it.
# On a stateless transport each request stands alone: the handshake carries
# ``clientInfo`` ("review-agent", "claude-ai") but tool calls do not, so they
# were attributed to the HTTP library ("python-httpx/0.28"). Keyed by caller
# and User-Agent, bounded, and expiring.
_CLIENT_MEMORY_TTL_S = 6 * 3600.0
_CLIENT_MEMORY_MAX = 4096
_client_memory: dict[tuple[str | None, str | None], tuple[str, str | None, float]] = {}


def remember_client(
    identity: AgentIdentity | None, name: str | None, version: str | None = None
) -> None:
    """Record the client name a caller announced in its handshake."""
    import time

    if not name or identity is None or not (identity.principal or identity.user_agent):
        return
    key = (identity.principal, identity.user_agent)
    _client_memory.pop(key, None)
    _client_memory[key] = (name, version, time.time())
    while len(_client_memory) > _CLIENT_MEMORY_MAX:
        _client_memory.pop(next(iter(_client_memory)))


def recall_client(identity: AgentIdentity | None) -> tuple[str, str | None] | None:
    """The client name this caller announced at its last handshake, if fresh."""
    import time

    if identity is None or not (identity.principal or identity.user_agent):
        return None
    hit = _client_memory.get((identity.principal, identity.user_agent))
    if hit is None or time.time() - hit[2] > _CLIENT_MEMORY_TTL_S:
        return None
    return hit[0], hit[1]


def merge_client_info(
    identity: AgentIdentity | None,
    client_name: str | None,
    client_version: str | None = None,
    *,
    protocol_version: str | None = None,
    capabilities: tuple[str, ...] | None = None,
    model: str | None = None,
) -> AgentIdentity:
    """Overlay MCP ``initialize`` data onto a header-parsed identity.

    The handshake's ``clientInfo`` is the most reliable signal of which harness
    is connected (Claude Code, Cursor, Codex, ...), so it takes precedence over
    the User-Agent parse for the ``client`` field. ``protocol_version`` and
    ``capabilities`` are spec-backed handshake fields. ``model`` — which MCP
    does not carry — is only set here when a caller resolved it out-of-band
    (e.g. an X-Model header) and never overwrites an existing value with None.
    """
    base = identity or AgentIdentity()
    has_name = bool(client_name and client_name.strip())
    # Nothing to overlay — return the input untouched (callers rely on identity).
    if not has_name and not protocol_version and capabilities is None and not model:
        return base
    name = client_name.strip().lower() if client_name and client_name.strip() else base.client
    return replace(
        base,
        client=name,
        client_version=client_version or base.client_version,
        protocol_version=protocol_version or base.protocol_version,
        capabilities=capabilities if capabilities is not None else base.capabilities,
        model=model or base.model,
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
