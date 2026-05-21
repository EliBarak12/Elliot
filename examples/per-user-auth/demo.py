"""End-to-end demo of per-user connector auth, with real-browser screenshots.

Flow proven here (Gmail-style connector):
  1. Agent calls a tool with no connected account -> actionable AUTH_REQUIRED
     carrying a connect URL.
  2. A real Chromium opens that URL -> Elliot redirects to the provider's
     OAuth consent -> user authorizes -> Elliot stores a per-user token.
  3. Agent lists tools and calls the tool again -> it fetches the *connected
     user's* data.
  4. A second user connects and sees only their own data (per-user isolation).

Run:  uv run python examples/per-user-auth/demo.py
Screenshots land in examples/per-user-auth/screenshots/.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
PROVIDER_PORT = 9700
RUNTIME_PORT = 9710
RUNTIME_BASE = f"http://127.0.0.1:{RUNTIME_PORT}"
PROVIDER_BASE = f"http://127.0.0.1:{PROVIDER_PORT}"
MCP_URL = f"{RUNTIME_BASE}/mcp/"


def _serve(app: Any, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    return server


def run_async(coro: Any) -> Any:
    """Run a coroutine in a dedicated thread/loop.

    The Playwright sync API runs its own event loop on this thread, so
    asyncio.run() here would fail; isolating MCP calls in another thread keeps
    the two loops apart.
    """
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
    raise RuntimeError(f"server at {url} did not come up")


# ── MCP client helpers ─────────────────────────────────────────────────────────


async def _mcp_call(user: str, tool: str, args: dict[str, Any]) -> tuple[bool, str]:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"X-Elliot-User": user}
    async with (
        streamablehttp_client(MCP_URL, headers=headers) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        res = await session.call_tool(tool, args)
        text = res.content[0].text if res.content else ""  # type: ignore[union-attr]
        return bool(res.isError), text


async def _mcp_list_tools() -> list[tuple[str, str]]:
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with (
        streamablehttp_client(MCP_URL, headers={"X-Elliot-User": "alice"}) as (r, w, _),
        ClientSession(r, w) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        return [(t.name, t.description or "") for t in tools.tools]


# ── rendering MCP results as screenshots ───────────────────────────────────────


def _render(page: Any, title: str, html_body: str, shot: str) -> None:
    page.set_content(
        "<!doctype html><meta charset='utf-8'>"
        "<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;"
        "color:#10131a;padding:0 20px}h2{font-size:20px}.box{background:#0d1117;color:#c9d1d9;"
        "padding:18px;border-radius:10px;font:13px ui-monospace,monospace;white-space:pre-wrap}"
        "table{border-collapse:collapse;width:100%;margin-top:8px}td,th{border:1px solid #ddd;"
        "padding:8px 10px;text-align:left;font-size:14px}th{background:#f3f4f6}"
        ".tag{display:inline-block;background:#4338ca;color:#fff;border-radius:6px;padding:2px 8px;"
        "font-size:12px}</style>"
        f"<h2>{title}</h2>{html_body}"
    )
    page.screenshot(path=str(SHOTS / shot), full_page=True)


def _messages_table(payload: dict[str, Any]) -> str:
    rows = payload.get("rows", [])
    head = "<tr><th>id</th><th>sender</th><th>subject</th><th>unread</th></tr>"
    body = "".join(
        f"<tr><td>{r.get('id')}</td><td>{r.get('sender')}</td>"
        f"<td>{r.get('subject')}</td><td>{r.get('unread')}</td></tr>"
        for r in rows
    )
    return f"<p><span class='tag'>{len(rows)} message(s)</span></p><table>{head}{body}</table>"


def _connect_via_browser(page: Any, connect_url: str, account: str, shot_prefix: str) -> None:
    page.goto(connect_url, wait_until="networkidle")
    _shot(page, f"{shot_prefix}_consent.png")
    page.fill("[data-testid=account]", account)
    page.click("[data-testid=authorize]")
    page.wait_for_load_state("networkidle")
    _shot(page, f"{shot_prefix}_connected.png")


def _shot(page: Any, name: str) -> None:
    page.screenshot(path=str(SHOTS / name), full_page=True)


def _extract_connect_url(text: str) -> str:
    m = re.search(r"https?://\S+", text)
    if not m:
        raise RuntimeError(f"no connect URL in error: {text}")
    return m.group(0).rstrip(".")


def main() -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    os.environ["MAILBOX_CLIENT_ID"] = "mailbox-client"
    os.environ["MAILBOX_CLIENT_SECRET"] = "mailbox-secret"
    os.environ["ELLIOT_SSRF_ALLOW_PRIVATE"] = "1"
    os.environ["ELLIOT_HTTP_DISABLE_PINNING"] = "1"
    os.environ["ELLIOT_PUBLIC_URL"] = RUNTIME_BASE
    os.environ["ELLIOT_VAULT_DB"] = str(HERE / ".vault.db")
    from cryptography.fernet import Fernet

    os.environ["ELLIOT_VAULT_KEY"] = Fernet.generate_key().decode()
    os.environ["ELLIOT_CONNECTOR"] = str(HERE / "connector.json")
    for stale in (HERE / ".vault.db",):
        stale.unlink(missing_ok=True)

    from mock_provider import app as provider_app

    from elliot_connector_runtime.server import create_app

    _serve(provider_app, PROVIDER_PORT)
    runtime_app = create_app(connector_path=str(HERE / "connector.json"), secrets={})
    _serve(runtime_app, RUNTIME_PORT)
    _wait(f"{PROVIDER_BASE}/health")
    _wait(f"{RUNTIME_BASE}/health")

    transcript: list[str] = []

    def log(msg: str) -> None:
        print(msg)
        transcript.append(msg)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 900, "height": 720})

        # 1. tools are visible before any auth
        tools = run_async(_mcp_list_tools())
        log(f"[1] tools/list -> {[t[0] for t in tools]}")
        _render(
            page,
            "1 · MCP tools/list (visible before auth)",
            "".join(f"<p><b>{n}</b><br><small>{d}</small></p>" for n, d in tools),
            "01_tools_list.png",
        )

        # 2. call as alice with no connected account -> AUTH_REQUIRED
        is_err, text = run_async(_mcp_call("alice", "list_messages", {}))
        log(f"[2] alice calls list_messages (not connected) -> isError={is_err}: {text}")
        _render(
            page,
            "2 · Tool call before connecting → actionable AUTH_REQUIRED",
            f"<div class='box'>{text}</div>",
            "02_auth_required.png",
        )
        connect_url = _extract_connect_url(text)

        # 3. alice connects her account in a real browser
        log(f"[3] alice opens connect URL: {connect_url}")
        _connect_via_browser(page, connect_url, "alice@mailbox.test", "03_alice")

        # 4. alice calls again -> her mailbox
        is_err, text = run_async(_mcp_call("alice", "list_messages", {}))
        payload = json.loads(text)
        log(f"[4] alice calls list_messages (connected) -> count={payload.get('count')}")
        _render(
            page,
            "4 · After connecting, the tool fetches Alice's mailbox",
            _messages_table(payload),
            "04_alice_messages.png",
        )

        # 5. bob connects his own account -> only his mail (isolation)
        is_err, text = run_async(_mcp_call("bob", "list_messages", {}))
        connect_url_bob = _extract_connect_url(text)
        log(f"[5] bob (not connected) -> AUTH_REQUIRED; opens {connect_url_bob}")
        _connect_via_browser(page, connect_url_bob, "bob@mailbox.test", "05_bob")
        is_err, text = run_async(_mcp_call("bob", "list_messages", {}))
        payload_bob = json.loads(text)
        log(f"[6] bob calls list_messages (connected) -> count={payload_bob.get('count')}")
        _render(
            page,
            "6 · Bob sees only Bob's mailbox (per-user isolation)",
            _messages_table(payload_bob),
            "06_bob_messages.png",
        )

        browser.close()

    (SHOTS / "transcript.txt").write_text("\n".join(transcript) + "\n")
    print("\nScreenshots + transcript written to", SHOTS)


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(HERE))
    main()
