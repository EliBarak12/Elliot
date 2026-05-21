"""Request-scoped, per-user credential resolution.

This is the architectural pivot for per-user auth: instead of one global
``secrets`` dict frozen into a single ``ToolExecutor``, the runtime resolves the
*calling user's* upstream credential per request and serves them an executor
bound to it. ``scope="shared"`` sources keep the original global behaviour.
"""

from __future__ import annotations

import asyncio
import os
from typing import Protocol

import structlog

from elliot_core.errors import ElliotError
from elliot_core.types import ConnectorConfig, SourceConfig

from .executor import ToolExecutor, _resolve_secret
from .oauth_flow import refresh_access_token
from .oauth_store import CredentialVault, StoredCredential

log = structlog.get_logger(__name__)


class ExecutorFactory(Protocol):
    def __call__(self, config: ConnectorConfig, secrets: dict[str, str]) -> ToolExecutor: ...


def _connector_slug(config: ConnectorConfig) -> str:
    return str(getattr(config, "slug", None) or getattr(config, "name", "connector"))


def _public_base_url() -> str:
    return os.environ.get("ELLIOT_PUBLIC_URL", "http://localhost:3001").rstrip("/")


class ExecutorPool:
    """Serves a ``ToolExecutor`` bound to the calling user's credentials.

    For connectors with no ``per_user`` source the pool returns one shared
    executor (unchanged behaviour). Otherwise it resolves the user's vault
    credentials (refreshing expired OAuth tokens), and raises ``AUTH_REQUIRED``
    with connect instructions when a credential is missing.
    """

    def __init__(
        self,
        config: ConnectorConfig,
        base_secrets: dict[str, str],
        vault: CredentialVault | None = None,
        executor_factory: ExecutorFactory = ToolExecutor,
    ) -> None:
        self._config = config
        self._base_secrets = base_secrets
        self._vault = vault
        self._factory = executor_factory
        self._slug = _connector_slug(config)
        self._per_user_sources: list[SourceConfig] = [
            s for s in config.sources if s.auth is not None and s.auth.scope == "per_user"
        ]
        self._shared_executor: ToolExecutor | None = None
        # user_id -> (secrets snapshot, executor) so a token refresh rebuilds.
        self._user_execs: dict[str, tuple[dict[str, str], ToolExecutor]] = {}
        self._lock = asyncio.Lock()

    @property
    def requires_user_auth(self) -> bool:
        return bool(self._per_user_sources)

    async def get_executor(self, user_id: str | None) -> ToolExecutor:
        if not self._per_user_sources:
            if self._shared_executor is None:
                self._shared_executor = self._factory(self._config, self._base_secrets)
            return self._shared_executor

        if not user_id:
            raise ElliotError(
                "AUTH_REQUIRED",
                (
                    f"The '{self._config.name}' connector authenticates each user "
                    "individually. Identify the end user with an 'X-Elliot-User' "
                    "header, then connect their account."
                ),
                {"connector": self._slug, "reason": "no_user_identity"},
            )

        async with self._lock:
            user_secrets, missing = await self._resolve_user_secrets(user_id)
            if missing:
                raise self._auth_required(user_id, missing)
            prev = self._user_execs.get(user_id)
            if prev is None or prev[0] != user_secrets:
                executor = self._factory(self._config, user_secrets)
                self._user_execs[user_id] = (user_secrets, executor)
                return executor
            return prev[1]

    async def _resolve_user_secrets(
        self, user_id: str
    ) -> tuple[dict[str, str], list[SourceConfig]]:
        secrets = dict(self._base_secrets)
        missing: list[SourceConfig] = []
        for source in self._per_user_sources:
            assert source.auth is not None
            cred = self._vault.get(user_id, self._slug, source.id) if self._vault else None
            if cred is None:
                missing.append(source)
                continue
            if cred.kind == "oauth2" and cred.is_expired():
                cred = await self._try_refresh(source, user_id)
                if cred is None:
                    missing.append(source)
                    continue
            secrets[source.auth.secret_key] = cred.secret
            log.info(
                "credential.resolved",
                user_id=user_id,
                connector=self._slug,
                source_id=source.id,
                kind=cred.kind,
            )
        return secrets, missing

    async def _try_refresh(self, source: SourceConfig, user_id: str) -> StoredCredential | None:
        assert (
            source.auth is not None and source.auth.oauth2 is not None and self._vault is not None
        )
        cred = self._vault.get(user_id, self._slug, source.id)
        if cred is None or not cred.refresh_token:
            return None
        oauth2 = source.auth.oauth2
        client_id = _resolve_secret(oauth2.client_id_secret, self._base_secrets)
        client_secret = _resolve_secret(oauth2.client_secret_secret, self._base_secrets)
        try:
            refreshed = await refresh_access_token(
                oauth2, cred, client_id=client_id, client_secret=client_secret
            )
        except Exception as exc:  # refresh failed -> force re-connect
            log.warning(
                "credential.refresh_failed",
                user_id=user_id,
                source_id=source.id,
                error=str(exc),
            )
            return None
        self._vault.put(refreshed)
        return refreshed

    def _auth_required(self, user_id: str, missing: list[SourceConfig]) -> ElliotError:
        base = _public_base_url()
        connect = []
        for source in missing:
            assert source.auth is not None
            connect.append(
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "auth_type": source.auth.type,
                    "connect_url": f"{base}/oauth/start/{source.id}?user={user_id}",
                }
            )
        lines = "; ".join(f"{c['source_name']}: open {c['connect_url']}" for c in connect)
        return ElliotError(
            "AUTH_REQUIRED",
            (
                "Connect your account to use this connector. Open the following "
                f"URL(s) in a browser, complete the login, then retry the tool — {lines}"
            ),
            {"connector": self._slug, "user_id": user_id, "connect": connect},
        )

    def invalidate(self, user_id: str) -> None:
        self._user_execs.pop(user_id, None)


__all__ = ["ExecutorPool"]
