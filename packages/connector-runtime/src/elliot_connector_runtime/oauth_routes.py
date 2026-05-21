"""HTTP endpoints that drive per-user connect flows (auth boundary 2).

Routes:
  GET  /oauth/start/{source_id}?user=<id>   begin connect (OAuth redirect or
                                            api-key paste form)
  GET  /oauth/callback/{source_id}          OAuth redirect target; exchanges
                                            the code for a per-user token
  POST /oauth/apikey/{source_id}            store a user-supplied API key
  GET  /oauth/status?user=<id>              per-source connection status

These are author-configured, user-facing endpoints — not agent/MCP traffic.
"""

from __future__ import annotations

import html
import time
from typing import Any

import structlog
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from elliot_core.types import ConnectorConfig, SourceConfig

from .credential_resolver import ExecutorPool
from .executor import _resolve_secret
from .oauth_flow import (
    PendingAuth,
    build_authorize_url,
    exchange_code,
    generate_pkce,
    new_state,
)
from .oauth_store import CredentialVault, StoredCredential

log = structlog.get_logger(__name__)

_PENDING_TTL_S = 600.0


def _public_base(request: Request) -> str:
    import os

    configured = os.environ.get("ELLIOT_PUBLIC_URL")
    if configured:
        return configured.rstrip("/")
    return str(request.base_url).rstrip("/")


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:560px;margin:64px auto;"
        "padding:0 20px;color:#1a1a2e}h1{font-size:22px}.card{background:#f5f5fa;"
        "border:1px solid #e0e0ee;border-radius:12px;padding:24px;margin-top:16px}"
        ".ok{color:#0a7d28}.btn{display:inline-block;background:#4338ca;color:#fff;"
        "padding:10px 18px;border-radius:8px;text-decoration:none;border:0;font-size:15px;"
        "cursor:pointer}input{width:100%;padding:10px;border:1px solid #ccc;border-radius:8px;"
        "font-size:14px;margin:8px 0 16px}</style></head>"
        f"<body><h1>{html.escape(title)}</h1><div class='card'>{body}</div></body></html>"
    )


def register_oauth_routes(
    app: FastAPI,
    config: ConnectorConfig,
    secrets: dict[str, str],
    vault: CredentialVault,
    pool: ExecutorPool,
) -> None:
    slug = getattr(config, "slug", None) or config.name
    sources: dict[str, SourceConfig] = {s.id: s for s in config.sources}
    pending: dict[str, PendingAuth] = {}

    def _sweep() -> None:
        now = time.time()
        for state in [s for s, p in pending.items() if now - p.created_at > _PENDING_TTL_S]:
            pending.pop(state, None)

    @app.get("/oauth/start/{source_id}")
    async def oauth_start(source_id: str, request: Request, user: str = "") -> Any:
        source = sources.get(source_id)
        if source is None or source.auth is None or source.auth.scope != "per_user":
            return JSONResponse(
                status_code=404,
                content={
                    "error": {"code": "NOT_FOUND", "message": f"No per-user source {source_id!r}"}
                },
            )
        if not user:
            return HTMLResponse(
                _page("Identify yourself", "<p>Missing <code>?user=</code> identifier.</p>"),
                status_code=400,
            )
        auth = source.auth
        base = _public_base(request)

        if auth.type == "oauth2":
            assert auth.oauth2 is not None
            client_id = _resolve_secret(auth.oauth2.client_id_secret, secrets)
            verifier, challenge = generate_pkce()
            state = new_state()
            redirect_uri = f"{base}/oauth/callback/{source_id}"
            pending[state] = PendingAuth(
                user_id=user,
                connector=slug,
                source_id=source_id,
                code_verifier=verifier,
                redirect_uri=redirect_uri,
                created_at=time.time(),
            )
            _sweep()
            url = build_authorize_url(
                auth.oauth2,
                client_id=client_id,
                redirect_uri=redirect_uri,
                state=state,
                code_challenge=challenge,
            )
            log.info("oauth.start", user_id=user, connector=slug, source_id=source_id)
            return RedirectResponse(url, status_code=302)

        # api_key / bearer / basic: render a paste form.
        action = f"{base}/oauth/apikey/{source_id}"
        body = (
            f"<p>Paste your <b>{html.escape(source.name)}</b> token to connect it for "
            f"user <code>{html.escape(user)}</code>.</p>"
            f"<form method='post' action='{action}'>"
            f"<input type='hidden' name='user' value='{html.escape(user)}'>"
            "<input name='token' placeholder='paste token' autofocus>"
            "<button class='btn' type='submit'>Connect</button></form>"
        )
        return HTMLResponse(_page(f"Connect {source.name}", body))

    @app.get("/oauth/callback/{source_id}")
    async def oauth_callback(
        source_id: str, request: Request, code: str = "", state: str = "", error: str = ""
    ) -> Any:
        if error:
            return HTMLResponse(
                _page("Authorization failed", f"<p>Provider returned: {html.escape(error)}</p>"),
                status_code=400,
            )
        info = pending.pop(state, None)
        if info is None or info.source_id != source_id:
            return HTMLResponse(
                _page("Invalid request", "<p>Unknown or expired authorization state.</p>"),
                status_code=400,
            )
        source = sources.get(source_id)
        assert source is not None and source.auth is not None and source.auth.oauth2 is not None
        oauth2 = source.auth.oauth2
        client_id = _resolve_secret(oauth2.client_id_secret, secrets)
        client_secret = _resolve_secret(oauth2.client_secret_secret, secrets)
        try:
            cred = await exchange_code(
                oauth2,
                client_id=client_id,
                client_secret=client_secret,
                code=code,
                code_verifier=info.code_verifier,
                redirect_uri=info.redirect_uri,
                user_id=info.user_id,
                connector=slug,
                source_id=source_id,
            )
        except Exception as exc:
            log.warning("oauth.exchange_failed", source_id=source_id, error=str(exc))
            return HTMLResponse(
                _page(
                    "Authorization failed", f"<p>Token exchange failed: {html.escape(str(exc))}</p>"
                ),
                status_code=502,
            )
        vault.put(cred)
        pool.invalidate(info.user_id)
        log.info("oauth.connected", user_id=info.user_id, connector=slug, source_id=source_id)
        return HTMLResponse(
            _page(
                "Connected",
                f"<p class='ok'>✓ {html.escape(source.name)} is connected for "
                f"<code>{html.escape(info.user_id)}</code>.</p>"
                "<p>Return to your agent and run the tool again — it now acts as you.</p>",
            )
        )

    @app.post("/oauth/apikey/{source_id}")
    async def oauth_apikey(source_id: str, user: str = Form(...), token: str = Form(...)) -> Any:
        source = sources.get(source_id)
        if source is None or source.auth is None or source.auth.scope != "per_user":
            return JSONResponse(
                status_code=404,
                content={
                    "error": {"code": "NOT_FOUND", "message": f"No per-user source {source_id!r}"}
                },
            )
        vault.put(
            StoredCredential(
                user_id=user,
                connector=slug,
                source_id=source_id,
                kind="api_key",
                secret=token,
            )
        )
        pool.invalidate(user)
        return HTMLResponse(
            _page(
                "Connected",
                f"<p class='ok'>✓ {html.escape(source.name)} key stored for "
                f"<code>{html.escape(user)}</code>.</p>",
            )
        )

    @app.get("/oauth/status")
    async def oauth_status(user: str = "") -> Any:
        out = []
        for source in config.sources:
            if source.auth is None or source.auth.scope != "per_user":
                continue
            cred = vault.get(user, slug, source.id) if user else None
            out.append(
                {
                    "source_id": source.id,
                    "source_name": source.name,
                    "auth_type": source.auth.type,
                    "connected": cred is not None,
                }
            )
        return JSONResponse({"connector": slug, "user": user, "sources": out})


__all__ = ["register_oauth_routes"]
