"""OAuth 2.1 authorization-code + PKCE helpers for per-user connector auth.

Elliot acts as an OAuth *client to the upstream provider* (auth boundary 2): it
runs the user through the provider's login/consent, then exchanges the code for
a per-user access/refresh token it stores in the vault. It never replays the
agent's boundary-1 token to the upstream (avoids the confused-deputy / token
passthrough anti-pattern).

The wire-level OAuth client primitives (PKCE, authorize-URL building, the token
POST, TLS policy) live in :mod:`elliot_core.oauth` so the design-time discover
flow and this runtime flow speak to upstreams identically. This module adds the
runtime-only concern: wrapping the token payload into an encrypted-vault
``StoredCredential``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from elliot_core.oauth import (
    build_authorize_url,
    exchange_code_for_tokens,
    generate_pkce,
    new_state,
    oauth_tls_verify,
)
from elliot_core.types import OAuth2Config

from .oauth_store import StoredCredential

# Backwards-compatible alias: callers/tests import ``_verify_tls`` from here.
_verify_tls = oauth_tls_verify


@dataclass
class PendingAuth:
    """State held between /oauth/start and /oauth/callback for one connect."""

    user_id: str
    connector: str
    source_id: str
    code_verifier: str
    redirect_uri: str
    created_at: float


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
    payload = await exchange_code_for_tokens(
        oauth2,
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        code_verifier=code_verifier,
        redirect_uri=redirect_uri,
    )
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
    from elliot_core.oauth import refresh_tokens

    payload = await refresh_tokens(
        oauth2,
        refresh_token=cred.refresh_token,
        client_id=client_id,
        client_secret=client_secret,
    )
    return _credential_from_token_response(
        user_id=cred.user_id,
        connector=cred.connector,
        source_id=cred.source_id,
        payload=payload,
        fallback_refresh=cred.refresh_token,
        scopes=cred.scopes,
    )


__all__ = [
    "PendingAuth",
    "build_authorize_url",
    "exchange_code",
    "generate_pkce",
    "new_state",
    "refresh_access_token",
]
