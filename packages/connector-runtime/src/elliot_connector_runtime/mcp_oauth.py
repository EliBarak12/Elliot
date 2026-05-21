"""Elliot as an MCP OAuth authorization server (auth boundary 1) — with the
upstream per-user connect (boundary 2) chained into the same flow.

When ``ELLIOT_MCP_OAUTH=1`` the runtime advertises OAuth on ``/mcp`` so a client
like Claude shows a native **Connect** button. Crucially, one Connect does two
things:

  1. Authenticates the end user *to Elliot* (this AS issues an Elliot access
     token bound to a fresh Elliot user id).
  2. While Elliot has the user in the browser, it runs them through every
     ``per_user`` upstream source's own OAuth/login and stores those tokens in
     the vault under that same Elliot user id.

So by the time Elliot hands the client its access token, Elliot is already
authenticated *into the user's connector*. Subsequent ``/mcp`` calls carry the
Elliot token; the runtime resolves the matching upstream credential per request.

Endpoints (all under the runtime root, enabled only in OAuth mode):
  GET  /.well-known/oauth-protected-resource[/mcp]   RFC 9728 resource metadata
  GET  /.well-known/oauth-authorization-server       RFC 8414 AS metadata
  POST /register                                     RFC 7591 dynamic client reg
  GET  /authorize                                    OAuth 2.1 + PKCE (chains upstream)
  GET  /authorize/upstream/callback                  upstream OAuth redirect target
  POST /authorize/upstream/apikey                    upstream api-key paste step
  POST /token                                        code/refresh -> Elliot token
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import html
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import structlog
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from elliot_core.types import ConnectorConfig, SourceConfig
from elliot_core.user_identity import reset_current_user_id, set_current_user_id

from .credential_resolver import ExecutorPool
from .executor import _resolve_secret
from .oauth_flow import build_authorize_url, exchange_code, generate_pkce, new_state
from .oauth_store import CredentialVault, StoredCredential

log = structlog.get_logger(__name__)

_CODE_TTL_S = 300.0
_ACCESS_TTL_S = 3600.0


def verify_pkce(verifier: str, challenge: str) -> bool:
    """RFC 7636 S256: base64url(sha256(verifier)) == challenge."""
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return secrets.compare_digest(expected, challenge)


@dataclass
class _Login:
    user_id: str
    client_id: str
    redirect_uri: str
    state: str
    code_challenge: str
    pending: list[str]  # per_user source ids still to connect
    created_at: float = field(default_factory=time.time)
    up_state: str | None = None
    up_verifier: str | None = None
    up_source: str | None = None


@dataclass
class _Code:
    user_id: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    created_at: float = field(default_factory=time.time)


class TokenStore:
    """In-memory OAuth state for the Elliot AS (single-process runtime)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, dict[str, Any]] = {}
        self._logins: dict[str, _Login] = {}
        self._login_by_upstate: dict[str, str] = {}
        self._codes: dict[str, _Code] = {}
        self._access: dict[str, tuple[str, float]] = {}
        self._refresh: dict[str, str] = {}

    # ── dynamic client registration ──────────────────────────────────────────
    def register_client(self, redirect_uris: list[str]) -> str:
        client_id = f"elliot-client-{secrets.token_urlsafe(12)}"
        with self._lock:
            self._clients[client_id] = {"redirect_uris": redirect_uris}
        return client_id

    def client_allows(self, client_id: str, redirect_uri: str) -> bool:
        with self._lock:
            client = self._clients.get(client_id)
        if client is None:
            return False
        uris = client.get("redirect_uris") or []
        return not uris or redirect_uri in uris

    # ── login sessions (the chained connect) ─────────────────────────────────
    def new_login(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        pending: list[str],
    ) -> tuple[str, _Login]:
        login_id = secrets.token_urlsafe(18)
        user_id = f"u-{secrets.token_urlsafe(12)}"
        login = _Login(
            user_id=user_id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            pending=pending,
        )
        with self._lock:
            self._logins[login_id] = login
        return login_id, login

    def get_login(self, login_id: str) -> _Login | None:
        with self._lock:
            return self._logins.get(login_id)

    def bind_upstream_state(self, up_state: str, login_id: str) -> None:
        with self._lock:
            self._login_by_upstate[up_state] = login_id

    def login_by_upstream_state(self, up_state: str) -> tuple[str, _Login] | None:
        with self._lock:
            login_id = self._login_by_upstate.get(up_state)
            login = self._logins.get(login_id) if login_id else None
        return (login_id, login) if login_id and login else None

    def drop_login(self, login_id: str) -> None:
        with self._lock:
            login = self._logins.pop(login_id, None)
            if login and login.up_state:
                self._login_by_upstate.pop(login.up_state, None)

    # ── authorization codes + tokens ─────────────────────────────────────────
    def issue_code(self, login: _Login) -> str:
        code = secrets.token_urlsafe(24)
        with self._lock:
            self._codes[code] = _Code(
                user_id=login.user_id,
                client_id=login.client_id,
                redirect_uri=login.redirect_uri,
                code_challenge=login.code_challenge,
            )
        return code

    def redeem_code(
        self, code: str, *, client_id: str, redirect_uri: str, code_verifier: str
    ) -> str | None:
        with self._lock:
            entry = self._codes.pop(code, None)
        if entry is None or time.time() - entry.created_at > _CODE_TTL_S:
            return None
        if entry.client_id != client_id or entry.redirect_uri != redirect_uri:
            return None
        if not verify_pkce(code_verifier, entry.code_challenge):
            return None
        return entry.user_id

    def mint_tokens(self, user_id: str) -> tuple[str, str]:
        access = f"elliot_at_{secrets.token_urlsafe(24)}"
        refresh = f"elliot_rt_{secrets.token_urlsafe(24)}"
        with self._lock:
            self._access[access] = (user_id, time.time() + _ACCESS_TTL_S)
            self._refresh[refresh] = user_id
        return access, refresh

    def refresh_tokens(self, refresh_token: str) -> tuple[str, str] | None:
        with self._lock:
            user_id = self._refresh.get(refresh_token)
        if not user_id:
            return None
        return self.mint_tokens(user_id)

    def validate_access(self, token: str) -> str | None:
        with self._lock:
            entry = self._access.get(token)
        if entry is None:
            return None
        user_id, expiry = entry
        if time.time() >= expiry:
            with self._lock:
                self._access.pop(token, None)
            return None
        return user_id


def _base_url(request: Request) -> str:
    configured = os.environ.get("ELLIOT_PUBLIC_URL")
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def _per_user_sources(config: ConnectorConfig) -> list[SourceConfig]:
    return [s for s in config.sources if s.auth is not None and s.auth.scope == "per_user"]


def register_mcp_oauth(
    app: FastAPI,
    config: ConnectorConfig,
    secrets_map: dict[str, str],
    vault: CredentialVault,
    pool: ExecutorPool,
    store: TokenStore,
) -> None:
    slug = getattr(config, "slug", None) or config.name
    sources: dict[str, SourceConfig] = {s.id: s for s in config.sources}

    def _resource_metadata(request: Request) -> dict[str, Any]:
        base = _base_url(request)
        return {
            "resource": f"{base}/mcp",
            "authorization_servers": [base],
            "bearer_methods_supported": ["header"],
        }

    @app.get("/.well-known/oauth-protected-resource")
    async def prm(request: Request) -> JSONResponse:
        return JSONResponse(_resource_metadata(request))

    @app.get("/.well-known/oauth-protected-resource/mcp")
    async def prm_mcp(request: Request) -> JSONResponse:
        return JSONResponse(_resource_metadata(request))

    @app.get("/.well-known/oauth-authorization-server")
    async def asm(request: Request) -> JSONResponse:
        base = _base_url(request)
        return JSONResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/authorize",
                "token_endpoint": f"{base}/token",
                "registration_endpoint": f"{base}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
            }
        )

    @app.post("/register")
    async def register(request: Request) -> JSONResponse:
        body = {}
        with contextlib.suppress(Exception):
            body = await request.json()
        redirect_uris = body.get("redirect_uris") or []
        client_id = store.register_client(redirect_uris)
        return JSONResponse(
            {
                "client_id": client_id,
                "client_id_issued_at": int(time.time()),
                "redirect_uris": redirect_uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
        )

    async def _continue(login_id: str, login: _Login, request: Request) -> Any:
        """Advance the chained connect: connect the next pending upstream source,
        or, when all are connected, issue the Elliot authorization code."""
        base = _base_url(request)
        if not login.pending:
            code = store.issue_code(login)
            store.drop_login(login_id)
            sep = "&" if "?" in login.redirect_uri else "?"
            target = f"{login.redirect_uri}{sep}{urlencode({'code': code, 'state': login.state})}"
            log.info("mcp_oauth.authorized", user_id=login.user_id, connector=slug)
            return RedirectResponse(target, status_code=302)

        source = sources[login.pending[0]]
        assert source.auth is not None
        if source.auth.type == "oauth2":
            assert source.auth.oauth2 is not None
            client_id = _resolve_secret(source.auth.oauth2.client_id_secret, secrets_map)
            verifier, challenge = generate_pkce()
            up_state = new_state()
            login.up_state, login.up_verifier, login.up_source = up_state, verifier, source.id
            store.bind_upstream_state(up_state, login_id)
            redirect_uri = f"{base}/authorize/upstream/callback"
            url = build_authorize_url(
                source.auth.oauth2,
                client_id=client_id,
                redirect_uri=redirect_uri,
                state=up_state,
                code_challenge=challenge,
            )
            return RedirectResponse(url, status_code=302)

        # api_key per_user source: paste form that posts back into the chain.
        body = (
            f"<p>Connect <b>{html.escape(source.name)}</b> to finish signing in.</p>"
            f"<form method='post' action='{base}/authorize/upstream/apikey'>"
            f"<input type='hidden' name='login' value='{html.escape(login_id)}'>"
            "<input name='token' placeholder='paste your API key' autofocus>"
            "<button class='btn' type='submit' data-testid='connect'>Connect</button></form>"
        )
        return HTMLResponse(_page(f"Connect {source.name}", body))

    @app.get("/authorize")
    async def authorize(
        request: Request,
        client_id: str = "",
        redirect_uri: str = "",
        state: str = "",
        code_challenge: str = "",
        code_challenge_method: str = "",
        response_type: str = "code",
    ) -> Any:
        if response_type != "code" or not code_challenge or code_challenge_method != "S256":
            return JSONResponse(
                {"error": "invalid_request", "error_description": "PKCE S256 code required"},
                status_code=400,
            )
        if not store.client_allows(client_id, redirect_uri):
            return JSONResponse(
                {"error": "invalid_client", "error_description": "unknown client/redirect_uri"},
                status_code=400,
            )
        pending = [s.id for s in _per_user_sources(config)]
        login_id, login = store.new_login(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=code_challenge,
            pending=pending,
        )
        log.info(
            "mcp_oauth.authorize_start", user_id=login.user_id, connector=slug, pending=pending
        )
        return await _continue(login_id, login, request)

    @app.get("/authorize/upstream/callback")
    async def upstream_callback(
        request: Request, code: str = "", state: str = "", error: str = ""
    ) -> Any:
        found = store.login_by_upstream_state(state)
        if found is None:
            return HTMLResponse(_page("Invalid request", "<p>Unknown sign-in state.</p>"), 400)
        login_id, login = found
        if error:
            store.drop_login(login_id)
            return HTMLResponse(_page("Sign-in cancelled", f"<p>{html.escape(error)}</p>"), 400)
        source = sources[login.up_source or ""]
        assert source.auth is not None and source.auth.oauth2 is not None
        oauth2 = source.auth.oauth2
        try:
            cred = await exchange_code(
                oauth2,
                client_id=_resolve_secret(oauth2.client_id_secret, secrets_map),
                client_secret=_resolve_secret(oauth2.client_secret_secret, secrets_map),
                code=code,
                code_verifier=login.up_verifier or "",
                redirect_uri=f"{_base_url(request)}/authorize/upstream/callback",
                user_id=login.user_id,
                connector=slug,
                source_id=source.id,
            )
        except Exception as exc:
            log.warning("mcp_oauth.upstream_exchange_failed", source_id=source.id, error=str(exc))
            store.drop_login(login_id)
            return HTMLResponse(_page("Sign-in failed", f"<p>{html.escape(str(exc))}</p>"), 502)
        vault.put(cred)
        pool.invalidate(login.user_id)
        login.pending = [s for s in login.pending if s != source.id]
        login.up_state = login.up_verifier = login.up_source = None
        return await _continue(login_id, login, request)

    @app.post("/authorize/upstream/apikey")
    async def upstream_apikey(
        request: Request, login: str = Form(...), token: str = Form(...)
    ) -> Any:
        login_obj = store.get_login(login)
        if login_obj is None or not login_obj.pending:
            return HTMLResponse(_page("Invalid request", "<p>Sign-in expired.</p>"), 400)
        source_id = login_obj.pending[0]
        vault.put(
            StoredCredential(
                user_id=login_obj.user_id,
                connector=slug,
                source_id=source_id,
                kind="api_key",
                secret=token,
            )
        )
        pool.invalidate(login_obj.user_id)
        login_obj.pending = login_obj.pending[1:]
        return await _continue(login, login_obj, request)

    @app.post("/token")
    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        grant = form.get("grant_type")
        if grant == "authorization_code":
            user_id = store.redeem_code(
                str(form.get("code", "")),
                client_id=str(form.get("client_id", "")),
                redirect_uri=str(form.get("redirect_uri", "")),
                code_verifier=str(form.get("code_verifier", "")),
            )
            if user_id is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            access, refresh = store.mint_tokens(user_id)
        elif grant == "refresh_token":
            pair = store.refresh_tokens(str(form.get("refresh_token", "")))
            if pair is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            access, refresh = pair
        else:
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
        return JSONResponse(
            {
                "access_token": access,
                "refresh_token": refresh,
                "token_type": "Bearer",
                "expires_in": int(_ACCESS_TTL_S),
            }
        )


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:520px;margin:64px auto;"
        "padding:0 20px;color:#1a1a2e}.btn{background:#4338ca;color:#fff;padding:10px 18px;"
        "border:0;border-radius:8px;font-size:15px;cursor:pointer;margin-top:12px}"
        "input{width:100%;padding:10px;border:1px solid #ccc;border-radius:8px;margin-top:8px}"
        ".card{background:#fff;border:1px solid #e0e0ee;border-radius:14px;padding:28px}"
        "</style></head><body><div class='card'>"
        f"<h2 style='margin-top:0'>{html.escape(title)}</h2>{body}</div></body></html>"
    )


class MCPAuthMiddleware:
    """Enforce an Elliot OAuth bearer on ``/mcp`` and bind its user id.

    Missing/invalid token -> 401 with a ``WWW-Authenticate`` header pointing at
    the protected-resource metadata, which is what makes an MCP client surface a
    Connect button. Other paths (metadata, /authorize, /token, /health) are
    public and pass through untouched.
    """

    def __init__(self, app: ASGIApp, store: TokenStore) -> None:
        self.app = app
        self._store = store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        if not path.startswith("/mcp") or method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        auth = headers.get("authorization", "")
        token = auth[len("Bearer ") :] if auth.startswith("Bearer ") else ""
        user_id = self._store.validate_access(token) if token else None
        if user_id is None:
            await self._challenge(scope, send)
            return
        ctx_token = set_current_user_id(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            with contextlib.suppress(LookupError, ValueError):
                reset_current_user_id(ctx_token)

    async def _challenge(self, scope: Scope, send: Send) -> None:
        base = os.environ.get("ELLIOT_PUBLIC_URL")
        if not base:
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            host = headers.get("host", "localhost")
            scheme = scope.get("scheme", "http")
            base = f"{scheme}://{host}"
        base = base.rstrip("/")
        meta = f"{base}/.well-known/oauth-protected-resource"
        body = json.dumps(
            {
                "error": {
                    "code": "UNAUTHENTICATED",
                    "message": "Connect your account to use this MCP server.",
                }
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", f'Bearer resource_metadata="{meta}"'.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = ["MCPAuthMiddleware", "TokenStore", "register_mcp_oauth", "verify_pkce"]
