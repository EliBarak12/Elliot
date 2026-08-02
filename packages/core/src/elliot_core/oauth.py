"""OAuth 2.1 authorization-code + PKCE *client* primitives.

Shared by the design-time discover flow (``elliot-mcp-plugin``) and the runtime
per-user connect flow (``elliot-connector-runtime``) so both speak to upstream
providers identically. Elliot always acts as an OAuth *client to the upstream*
provider — it runs the user through the provider's login/consent and exchanges
the resulting code for a token. It never replays a caller's token to the
upstream (avoids the confused-deputy / token-passthrough anti-pattern).

These helpers are deliberately credential-store agnostic: they return the raw
token-endpoint payload. The runtime wraps that into its encrypted-vault
``StoredCredential``; the design-time discover flow uses the access token once,
just to fetch sample rows, and throws it away.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from elliot_core.secrets import host_env_secrets_allowed
from elliot_core.types import OAuth2Config

log = structlog.get_logger(__name__)

_TOKEN_TIMEOUT_S = 15.0


def generate_pkce() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for PKCE S256 (RFC 7636)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def new_state() -> str:
    """Return an unguessable ``state`` value for CSRF protection."""
    return secrets.token_urlsafe(24)


def build_authorize_url(
    oauth2: OAuth2Config,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    """Build the upstream authorization-endpoint URL (RFC 6749 + PKCE)."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if oauth2.scopes:
        params["scope"] = " ".join(oauth2.scopes)
    sep = "&" if "?" in oauth2.authorization_url else "?"
    return f"{oauth2.authorization_url}{sep}{urlencode(params)}"


def oauth_tls_verify() -> bool:
    """Whether to verify TLS certificates on OAuth token exchanges (default on).

    ``ELLIOT_OAUTH_INSECURE=1`` disables verification for a local demo/test
    provider only. It is *ignored* in the multi-tenant cloud — signalled by
    ``ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS=1`` — because a shared host must never
    turn off certificate verification for credential exchanges, which would
    expose every tenant's OAuth tokens to a man-in-the-middle.
    """
    if not host_env_secrets_allowed():
        return True
    return os.environ.get("ELLIOT_OAUTH_INSECURE", "") != "1"


async def exchange_code_for_tokens(
    oauth2: OAuth2Config,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens (RFC 6749 §4.1.3).

    Returns the raw token-endpoint JSON payload (``access_token``,
    ``refresh_token``, ``expires_in``, ...). The ``Accept: application/json``
    header coaxes providers that otherwise default to a form-encoded body
    (e.g. GitHub) into returning JSON.
    """
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_S, verify=oauth_tls_verify()) as client:
        resp = await client.post(
            oauth2.token_url, data=data, headers={"Accept": "application/json"}
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
    return payload


async def refresh_tokens(
    oauth2: OAuth2Config,
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> dict[str, Any]:
    """Mint a fresh access token from a refresh token (RFC 6749 §6)."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_S, verify=oauth_tls_verify()) as client:
        resp = await client.post(
            oauth2.token_url, data=data, headers={"Accept": "application/json"}
        )
        resp.raise_for_status()
        payload: dict[str, Any] = resp.json()
    return payload


__all__ = [
    "build_authorize_url",
    "exchange_code_for_tokens",
    "generate_pkce",
    "new_state",
    "oauth_tls_verify",
    "refresh_tokens",
]
