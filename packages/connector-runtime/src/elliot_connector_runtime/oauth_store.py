"""Per-user credential vault for connector auth boundary 2.

Stores each end user's *upstream* credential — an OAuth access/refresh token or
a user-supplied API key — keyed by ``(user_id, connector, source)``. Token
values are encrypted at rest with Fernet so a leaked DB file does not leak live
credentials. The encryption key comes from ``ELLIOT_VAULT_KEY``; for local dev a
key is generated and a warning logged (such a key does not survive restart).

Never log the decrypted secret — only boundary events (resolved / stored).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken

log = structlog.get_logger(__name__)

_VAULT_KEY_ENV = "ELLIOT_VAULT_KEY"


@dataclass
class StoredCredential:
    """A single end user's upstream credential for one connector source."""

    user_id: str
    connector: str
    source_id: str
    kind: str  # "oauth2" | "api_key"
    secret: str  # access token or api key (decrypted)
    refresh_token: str | None = None
    expires_at: float | None = None  # epoch seconds; None = never expires
    scopes: list[str] = field(default_factory=list)

    def is_expired(self, leeway_seconds: float = 60.0) -> bool:
        """Whether an OAuth access token is at/near expiry and needs refresh."""
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - leeway_seconds)


def _load_fernet() -> Fernet:
    key = os.environ.get(_VAULT_KEY_ENV)
    if not key:
        key = Fernet.generate_key().decode()
        log.warning(
            "vault.ephemeral_key",
            msg=(
                f"{_VAULT_KEY_ENV} is unset — generated an ephemeral key. Stored "
                "credentials will not be decryptable after restart. Set "
                f"{_VAULT_KEY_ENV} in production."
            ),
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


class CredentialVault:
    """SQLite-backed, encrypted-at-rest per-user credential store."""

    def __init__(self, db_path: str = ".elliot/credentials.db") -> None:
        self._db_path = db_path
        self._fernet = _load_fernet()
        self._lock = threading.Lock()
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: tool calls run in a threadpool, and access is
        # serialised by self._lock anyway.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
                user_id     TEXT NOT NULL,
                connector   TEXT NOT NULL,
                source_id   TEXT NOT NULL,
                kind        TEXT NOT NULL,
                secret_enc  BLOB NOT NULL,
                refresh_enc BLOB,
                expires_at  REAL,
                scopes      TEXT NOT NULL DEFAULT '',
                updated_at  REAL NOT NULL,
                PRIMARY KEY (user_id, connector, source_id)
            )
            """
        )
        self._conn.commit()

    def _enc(self, value: str | None) -> bytes | None:
        if value is None:
            return None
        return self._fernet.encrypt(value.encode())

    def _dec(self, blob: bytes | None) -> str | None:
        if blob is None:
            return None
        try:
            return self._fernet.decrypt(blob).decode()
        except InvalidToken:
            # Key rotated / ephemeral key lost across restart — treat as absent
            # so the user is re-prompted to connect rather than crashing.
            log.warning("vault.decrypt_failed")
            return None

    def get(self, user_id: str, connector: str, source_id: str) -> StoredCredential | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT kind, secret_enc, refresh_enc, expires_at, scopes "
                "FROM user_credentials WHERE user_id=? AND connector=? AND source_id=?",
                (user_id, connector, source_id),
            ).fetchone()
        if row is None:
            return None
        kind, secret_enc, refresh_enc, expires_at, scopes = row
        secret = self._dec(secret_enc)
        if secret is None:
            return None
        return StoredCredential(
            user_id=user_id,
            connector=connector,
            source_id=source_id,
            kind=kind,
            secret=secret,
            refresh_token=self._dec(refresh_enc),
            expires_at=expires_at,
            scopes=[s for s in (scopes or "").split(",") if s],
        )

    def put(self, cred: StoredCredential) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO user_credentials "
                "(user_id, connector, source_id, kind, secret_enc, refresh_enc, "
                " expires_at, scopes, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    cred.user_id,
                    cred.connector,
                    cred.source_id,
                    cred.kind,
                    self._enc(cred.secret),
                    self._enc(cred.refresh_token),
                    cred.expires_at,
                    ",".join(cred.scopes),
                    time.time(),
                ),
            )
            self._conn.commit()
        log.info(
            "vault.stored",
            user_id=cred.user_id,
            connector=cred.connector,
            source_id=cred.source_id,
            kind=cred.kind,
        )

    def delete(self, user_id: str, connector: str, source_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM user_credentials WHERE user_id=? AND connector=? AND source_id=?",
                (user_id, connector, source_id),
            )
            self._conn.commit()


__all__ = ["CredentialVault", "StoredCredential"]
