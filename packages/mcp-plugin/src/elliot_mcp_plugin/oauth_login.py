"""Design-time interactive OAuth login for ``elliot_discover_source``.

When a builder points Elliot at an OAuth-protected REST API, the discover phase
needs *some* token to fetch sample rows and learn the schema. Rather than asking
the builder to paste one (the inconsistency: end users never have to), Elliot
runs the builder through the same browser-redirect login their end users will
get at runtime.

This is the OAuth-for-native-apps pattern (RFC 8252): Elliot opens an ephemeral
loopback HTTP listener on ``127.0.0.1``, hands the agent an authorize URL to
surface to the builder, and catches the provider's redirect on the loopback
port. The resulting access token is used **only** to fetch discovery samples and
is held in memory for the session — it is never written into the connector file.
The connector itself keeps ``scope: per_user`` so end users authenticate
themselves at runtime.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import structlog

from elliot_core.oauth import (
    build_authorize_url,
    exchange_code_for_tokens,
    generate_pkce,
    new_state,
)
from elliot_core.types import OAuth2Config

log = structlog.get_logger(__name__)

# How long a started login stays valid before the builder must restart it.
LOGIN_TTL_S = 600.0


def _login_wait_s() -> float:
    """Seconds a single discover call blocks waiting for the builder to log in.

    Kept well under typical MCP client call timeouts: if the builder is slow,
    discover returns ``AUTH_REQUIRED`` ("still waiting") and the agent simply
    retries — the login state (and any token already captured) persists across
    retries, so a slow human login never loses progress.
    """
    raw = os.environ.get("ELLIOT_OAUTH_LOGIN_WAIT_S", "")
    try:
        return max(1.0, float(raw)) if raw else 120.0
    except ValueError:
        return 120.0


@dataclass
class BuildOAuthLogin:
    """One in-flight (or completed) builder OAuth login, keyed by source name."""

    name: str
    connect_id: str
    oauth2: OAuth2Config
    client_id: str
    client_secret: str
    verifier: str
    state: str
    redirect_uri: str
    authorize_url: str
    server: ThreadingHTTPServer
    event: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)
    code: str | None = None
    error: str | None = None
    _token: str | None = None
    _exchange_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def completed(self) -> bool:
        return self._token is not None

    def shutdown(self) -> None:
        """Stop the loopback listener. Safe to call more than once."""
        try:
            self.server.shutdown()
            self.server.server_close()
        except Exception:  # pragma: no cover - best-effort teardown
            log.debug("oauth_login.shutdown_failed", name=self.name)

    async def wait_and_exchange(self, timeout: float | None = None) -> str:
        """Block until the builder finishes logging in, then return the token.

        Returns the cached access token immediately on repeat calls. Raises
        ``TimeoutError`` if the redirect hasn't arrived within ``timeout``, or
        ``RuntimeError`` if the provider reported an error or returned no token.
        """
        if self._token is not None:
            return self._token
        wait = _login_wait_s() if timeout is None else timeout
        loop = asyncio.get_running_loop()
        got = await loop.run_in_executor(None, self.event.wait, wait)
        if not got:
            raise TimeoutError("login not completed yet")
        if self.error:
            raise RuntimeError(self.error)
        async with self._exchange_lock:
            if self._token is not None:
                return self._token
            if not self.code:
                raise RuntimeError("no authorization code was received")
            payload = await exchange_code_for_tokens(
                self.oauth2,
                client_id=self.client_id,
                client_secret=self.client_secret,
                code=self.code,
                code_verifier=self.verifier,
                redirect_uri=self.redirect_uri,
            )
            token = str(payload.get("access_token") or "")
            if not token:
                raise RuntimeError("token endpoint returned no access_token")
            self._token = token
        return self._token


def _make_handler(get_login: Callable[[], BuildOAuthLogin | None]) -> type[BaseHTTPRequestHandler]:
    class _CallbackHandler(BaseHTTPRequestHandler):
        # Silence the default stderr request logging — it would leak the
        # callback URL (which carries the authorization code) to the console.
        def log_message(self, *_args: object) -> None:  # noqa: D401
            return

        def _page(self, status: int, message: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            body = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Elliot</title><style>body{font-family:system-ui,sans-serif;"
                "max-width:480px;margin:64px auto;padding:0 20px;color:#1a1a2e}"
                ".card{background:#fff;border:1px solid #e0e0ee;border-radius:14px;"
                "padding:28px}</style></head><body><div class='card'>"
                f"<h2 style='margin-top:0'>Elliot</h2><p>{message}</p></div></body></html>"
            )
            self.wfile.write(body.encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            parsed = urlsplit(self.path)
            if parsed.path != "/callback":
                self._page(404, "Not found.")
                return
            login = get_login()
            qs = parse_qs(parsed.query)
            state = (qs.get("state") or [""])[0]
            if login is None or not state or state != login.state:
                self._page(400, "Invalid or expired sign-in state.")
                return
            err = (qs.get("error_description") or qs.get("error") or [""])[0]
            if err:
                login.error = err
                login.event.set()
                self._page(400, "Sign-in was cancelled or failed. You can close this tab.")
                return
            login.code = (qs.get("code") or [""])[0]
            login.event.set()
            self._page(
                200,
                "You're signed in. You can close this tab and return to your agent.",
            )

    return _CallbackHandler


def start_login(
    *,
    oauth2: OAuth2Config,
    client_id: str,
    client_secret: str,
    name: str,
    connect_id: str,
) -> BuildOAuthLogin:
    """Start a loopback OAuth login and return its state (incl. authorize_url).

    Binds an ephemeral ``127.0.0.1`` port for the redirect, generates PKCE +
    state, and serves the callback on a daemon thread.
    """
    holder: list[BuildOAuthLogin] = []
    handler = _make_handler(lambda: holder[0] if holder else None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = int(server.server_address[1])
    verifier, challenge = generate_pkce()
    state = new_state()
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    authorize_url = build_authorize_url(
        oauth2,
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=challenge,
    )
    login = BuildOAuthLogin(
        name=name,
        connect_id=connect_id,
        oauth2=oauth2,
        client_id=client_id,
        client_secret=client_secret,
        verifier=verifier,
        state=state,
        redirect_uri=redirect_uri,
        authorize_url=authorize_url,
        server=server,
    )
    holder.append(login)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"elliot-oauth-callback-{port}",
        daemon=True,
    )
    thread.start()
    log.info("oauth_login.started", name=name, connect_id=connect_id, port=port)
    return login


__all__ = ["LOGIN_TTL_S", "BuildOAuthLogin", "start_login"]
