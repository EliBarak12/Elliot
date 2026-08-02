"""End-to-end demo of the native MCP OAuth "Connect" flow (auth boundary 1)
chained with the upstream per-user connect (boundary 2).

This simulates exactly what a client like Claude does:
  1. Call /mcp with no token -> 401 + WWW-Authenticate (the Connect trigger).
  2. Discover protected-resource + authorization-server metadata.
  3. Dynamically register, then open /authorize in a browser.
  4. Elliot chains the user through the upstream MailBox OAuth consent, stores
     that token, then issues ITS OWN code back to the client's redirect_uri.
  5. Exchange the code for an Elliot access token.
  6. Call /mcp with the bearer -> tools fetch the connected user's mailbox.

One Connect => user authenticated to Elliot AND Elliot authenticated into the
user's connector.

Run:  uv run python dev/examples/per-user-auth/demo_mcp_oauth.py
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
PROVIDER_PORT, RUNTIME_PORT, CLIENT_PORT = 9700, 9710, 9712
RUNTIME_BASE = f"http://127.0.0.1:{RUNTIME_PORT}"
PROVIDER_BASE = f"http://127.0.0.1:{PROVIDER_PORT}"
CLIENT_REDIRECT = f"http://127.0.0.1:{CLIENT_PORT}/callback"
MCP_URL = f"{RUNTIME_BASE}/mcp/"

# Captures the authorization code the browser is redirected back with.
_captured: dict[str, str] = {}


def _client_app() -> FastAPI:
    app = FastAPI()

    @app.get("/callback")
    async def callback(request: Request) -> HTMLResponse:
        _captured.update(dict(request.query_params))
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><body style='font-family:system-ui;"
            "max-width:520px;margin:64px auto'><div style='background:#fff;border:1px solid #e0e0ee;"
            "border-radius:14px;padding:28px'><h2>Connected to your AI client</h2>"
            "<p style='color:#0a7d28'>✓ Authorization complete — you can close this window "
            "and return to the agent.</p></div></body>"
        )

    return app


def _serve(app: Any, port: int) -> None:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()


def run_async(coro: Any) -> Any:
    box: dict[str, Any] = {}

    def runner() -> None:
        box["v"] = asyncio.run(coro)

    t = threading.Thread(target=runner)
    t.start()
    t.join()
    return box["v"]


def _wait(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"{url} did not come up")


async def _mcp_list_and_fetch(access: str) -> tuple[list[str], dict[str, Any]]:
    import httpx2
    from mcp.client import Client
    from mcp.client.streamable_http import streamable_http_client

    http_client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {access}"})
    transport = streamable_http_client(MCP_URL, http_client=http_client)
    async with http_client, Client(transport, mode="legacy") as client:
        tools = await client.list_tools()
        res = await client.call_tool("list_messages", {})
        text = res.content[0].text if res.content else "{}"  # type: ignore[union-attr]
        return [t.name for t in tools.tools], json.loads(text)


def _render(page: Any, title: str, body_html: str, shot: str) -> None:
    page.set_content(
        "<!doctype html><meta charset=utf-8>"
        "<style>body{font-family:system-ui,sans-serif;max-width:780px;margin:40px auto;"
        "padding:0 20px;color:#10131a}h2{font-size:20px}.box{background:#0d1117;color:#c9d1d9;"
        "padding:18px;border-radius:10px;font:12.5px ui-monospace,monospace;white-space:pre-wrap}"
        "table{border-collapse:collapse;width:100%;margin-top:8px}td,th{border:1px solid #ddd;"
        "padding:8px 10px;text-align:left;font-size:14px}th{background:#f3f4f6}"
        ".tag{display:inline-block;background:#4338ca;color:#fff;border-radius:6px;padding:2px 8px}"
        f"</style><h2>{title}</h2>{body_html}"
    )
    page.screenshot(path=str(SHOTS / shot), full_page=True)


def _mailbox_table(payload: dict[str, Any]) -> str:
    rows = payload.get("rows", [])
    head = "<tr><th>id</th><th>sender</th><th>subject</th><th>unread</th></tr>"
    body = "".join(
        f"<tr><td>{r.get('id')}</td><td>{r.get('sender')}</td>"
        f"<td>{r.get('subject')}</td><td>{r.get('unread')}</td></tr>"
        for r in rows
    )
    return f"<p><span class='tag'>{len(rows)} message(s)</span></p><table>{head}{body}</table>"


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        MAILBOX_CLIENT_ID="mailbox-client",
        MAILBOX_CLIENT_SECRET="mailbox-secret",
        ELLIOT_SSRF_ALLOW_PRIVATE="1",
        ELLIOT_HTTP_DISABLE_PINNING="1",
        ELLIOT_PUBLIC_URL=RUNTIME_BASE,
        ELLIOT_MCP_OAUTH="1",
        ELLIOT_VAULT_DB=str(HERE / ".vault_oauth.db"),
        ELLIOT_CONNECTOR=str(HERE / "connector.json"),
    )
    from cryptography.fernet import Fernet

    os.environ["ELLIOT_VAULT_KEY"] = Fernet.generate_key().decode()
    (HERE / ".vault_oauth.db").unlink(missing_ok=True)

    from mock_provider import app as provider_app

    from elliot_connector_runtime.server import create_app

    _serve(provider_app, PROVIDER_PORT)
    _serve(_client_app(), CLIENT_PORT)
    _serve(create_app(connector_path=str(HERE / "connector.json"), secrets={}), RUNTIME_PORT)
    _wait(f"{PROVIDER_BASE}/health")
    _wait(f"{RUNTIME_BASE}/health")
    _wait(f"http://127.0.0.1:{CLIENT_PORT}/callback")

    from playwright.sync_api import sync_playwright

    from elliot_connector_runtime.oauth_flow import generate_pkce

    transcript: list[str] = []

    def log(m: str) -> None:
        print(m)
        transcript.append(m)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 720})

        # 1. unauthenticated /mcp -> 401 challenge (what makes Claude show Connect)
        unauth = httpx.get(MCP_URL, headers={"Accept": "text/event-stream"})
        log(f"[1] GET /mcp unauthenticated -> {unauth.status_code}")
        _render(
            page,
            "1 · Unauthenticated /mcp → 401 (client shows a Connect button)",
            f"<div class='box'>HTTP {unauth.status_code}\nWWW-Authenticate: "
            f"{unauth.headers.get('www-authenticate', '')}</div>",
            "oauth_01_challenge.png",
        )

        # 2. discovery
        prm = httpx.get(f"{RUNTIME_BASE}/.well-known/oauth-protected-resource").json()
        asm = httpx.get(f"{RUNTIME_BASE}/.well-known/oauth-authorization-server").json()
        log(f"[2] discovered AS: {asm['authorization_endpoint']}")
        _render(
            page,
            "2 · OAuth discovery (RFC 9728 + RFC 8414)",
            f"<div class='box'>protected-resource:\n{json.dumps(prm, indent=2)}\n\n"
            f"authorization-server:\n{json.dumps(asm, indent=2)}</div>",
            "oauth_02_discovery.png",
        )

        # 3. dynamic client registration
        client_id = httpx.post(
            asm["registration_endpoint"], json={"redirect_uris": [CLIENT_REDIRECT]}
        ).json()["client_id"]
        log(f"[3] registered client_id={client_id}")

        # 4. open /authorize in the browser (chains upstream consent)
        verifier, challenge = generate_pkce()
        authorize_url = (
            asm["authorization_endpoint"]
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": CLIENT_REDIRECT,
                    "state": "claude-state",
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        page.goto(authorize_url, wait_until="domcontentloaded")
        page.wait_for_selector("[data-testid=authorize]")
        _render_path = "oauth_03_upstream_consent.png"
        page.screenshot(path=str(SHOTS / _render_path), full_page=True)
        log("[4] browser landed on upstream MailBox consent (chained from /authorize)")
        page.fill("[data-testid=account]", "alice@mailbox.test")
        page.click("[data-testid=authorize]")
        page.wait_for_load_state("networkidle")
        page.screenshot(path=str(SHOTS / "oauth_04_client_connected.png"), full_page=True)

        code = _captured.get("code", "")
        log(f"[5] client received Elliot authorization code (len={len(code)})")

        # 5. exchange code for an Elliot access token
        tok = httpx.post(
            asm["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": CLIENT_REDIRECT,
                "code_verifier": verifier,
            },
        ).json()
        access = tok["access_token"]
        log(f"[6] exchanged for Elliot access token (len={len(access)})")

        # 6. call /mcp with the bearer -> tools fetch the connected user's mailbox
        tools, payload = run_async(_mcp_list_and_fetch(access))
        log(f"[7] /mcp tools={tools} ; list_messages -> {payload.get('count')} messages")
        _render(
            page,
            "5 · One Connect later: /mcp bearer call fetches the user's mailbox",
            _mailbox_table(payload),
            "oauth_05_mailbox.png",
        )

        browser.close()

    (SHOTS / "transcript_mcp_oauth.txt").write_text("\n".join(transcript) + "\n")
    print("\nScreenshots + transcript written to", SHOTS)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(HERE))
    main()
