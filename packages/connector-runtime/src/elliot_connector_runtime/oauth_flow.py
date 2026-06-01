"""OAuth 2.1 authorization-code + PKCE helpers for per-user connector auth.

Elliot acts as an OAuth *client to the upstream provider* (auth boundary 2): it
runs the user through the provider's login/consent, then exchanges the code for
a per-user access/refresh token it stores in the vault. It never replays the
agent's boundary-1 token to the upstream (avoids the confused-deputy / token
passthrough anti-pattern).
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from elliot_core.types import OAuth2Config

from .oauth_store import StoredCredential

_TOKEN_TIMEOUT_S = 15.0


@dataclass
class PendingAuth:
    """State held between /oauth/start and /oauth/callback for one connect."""

    user_id: str
    connector: str
    source_id: str
    code_verifier: str
    redirect_uri: str
    created_at: float


def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def new_state() -> str:
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


def _credential_from_token_response(
    *,
    user_id: str,
    connector: str,
    source_id: str,
    payload: dict[str, object],
    fallback_refresh: str | None = None,
    scopes: list[str] | None = None,
) -> StoredCredential:
    access = str(payload.get("access_token") or "")
    refresh = payload.get("refresh_token")
    refresh_str = str(refresh) if refresh else fallback_refresh
    expires_at: float | None = None
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)) or (
        isinstance(expires_in, str) and expires_in.isdigit()
    ):
        expires_at = time.time() + float(expires_in)
    return StoredCredential(
        user_id=user_id,
        connector=connector,
        source_id=source_id,
        kind="oauth2",
        secret=access,
        refresh_token=refresh_str,
        expires_at=expires_at,
        scopes=scopes or [],
    )


async def exchange_code(
    oauth2: OAuth2Config,
    *,
    client_id: str,
    client_secret: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
    user_id: str,
    connector: str,
    source_id: str,
) -> StoredCredential:
    """Exchange an authorization code for a per-user token (RFC 6749 §4.1.3)."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_S, verify=_verify_tls()) as client:
        resp = await client.post(oauth2.token_url, data=data)
        resp.raise_for_status()
        payload = resp.json()
    return _credential_from_token_response(
        user_id=user_id,
        connector=connector,
        source_id=source_id,
        payload=payload,
        scopes=oauth2.scopes,
    )


async def refresh_access_token(
    oauth2: OAuth2Config,
    cred: StoredCredential,
    *,
    client_id: str,
    client_secret: str,
) -> StoredCredential:
    """Use the stored refresh token to mint a fresh access token."""
    if not cred.refresh_token:
        raise ValueError("no refresh_token available")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": cred.refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient(timeout=_TOKEN_TIMEOUT_S, verify=_verify_tls()) as client:
        resp = await client.post(oauth2.token_url, data=data)
        resp.raise_for_status()
        payload = resp.json()
    return _credential_from_token_response(
        user_id=cred.user_id,
        connector=cred.connector,
        source_id=cred.source_id,
        payload=payload,
        fallback_refresh=cred.refresh_token,
        scopes=cred.scopes,
    )


def _verify_tls() -> bool:
    """Whether to verify TLS certificates on OAuth token exchanges (default on).

    ``ELLIOT_OAUTH_INSECURE=1`` disables verification for a local demo/test
    provider only. It is *ignored* in the multi-tenant cloud — signalled by
    ``ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS=1`` — because a shared host must never
    turn off certificate verification for credential exchanges, which would
    expose every tenant's OAuth tokens to a man-in-the-middle.
    """
    cloud = os.environ.get("ELLIOT_RUNTIME_NO_HOST_ENV_SECRETS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if cloud:
        return True
    return os.environ.get("ELLIOT_OAUTH_INSECURE", "") != "1"


__all__ = [
    "PendingAuth",
    "build_authorize_url",
    "exchange_code",
    "generate_pkce",
    "new_state",
    "refresh_access_token",
]
