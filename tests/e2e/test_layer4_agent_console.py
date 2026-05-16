"""Layer 4 E2E: the Agent Console — grouped multi-step sessions + live feed.

Proves the observability fix end to end over the real MCP wire protocol:

1. Build + export a connector and boot the runtime on :3001.
2. A consumer agent opens ONE streamable-HTTP MCP session and makes several
   tool calls — including failures and repeats.
3. ``GET /v1/sessions`` returns exactly ONE session that groups every call
   (previously each call was its own one-step session).
4. The session carries derived ``signals`` and a ``summary``.
5. ``GET /v1/sessions/stream`` serves a Server-Sent Events snapshot.
6. Playwright renders ``/console`` and screenshots the live trace.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack
from .test_layer1_mcp_protocol import BUSINESS_TOOLS, SOURCE_DEFS

RUNTIME_MCP_URL = "http://127.0.0.1:3001/mcp/"
RUNTIME_URL = "http://127.0.0.1:3001"
CONNECTOR_SLUG = "console-demo"

# users → list_active_enterprise_customers, orders → customer_order_history.
_SOURCES = [SOURCE_DEFS[0], SOURCE_DEFS[2]]
_TOOLS = [BUSINESS_TOOLS[0], BUSINESS_TOOLS[2]]

# One consumer agent's run — five tool calls over a single MCP connection,
# with two identical repeats so the redundant-call signal fires.
_CONSUMER_CALLS: list[tuple[str, dict]] = [
    ("list_active_enterprise_customers", {}),
    ("customer_order_history", {"customer_id": 1}),
    ("customer_order_history", {"customer_id": 3}),
    ("customer_order_history", {"customer_id": 1}),  # repeat → redundant signal
    ("list_active_enterprise_customers", {}),  # repeat → redundant signal
]


@pytest.fixture(scope="module")
def console_stack(api_base_url: str) -> Iterator[StackEndpoints]:
    """Plugin + Studio up; runtime booted via elliot_start_runtime after seed."""
    with elliot_stack(skip_studio=False, skip_runtime=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


@pytest.fixture(scope="module")
def consumer_session(console_stack: StackEndpoints, api_base_url: str) -> StackEndpoints:
    """Build a connector, boot its runtime, and drive one consumer agent run."""
    connector_path = console_stack.workspace / "connectors" / f"{CONNECTOR_SLUG}.connector.json"

    async def _build_and_run() -> None:
        async with open_mcp_session(console_stack.plugin_mcp_url) as session:
            for name, path, extra in _SOURCES:
                cfg: dict = {"url": f"{api_base_url}{path}"}
                cfg.update(extra)
                await call_tool_json(
                    session,
                    "elliot_discover_source",
                    {"source_type": "rest", "config": cfg, "name": name},
                )
            for tool in _TOOLS:
                await call_tool_json(session, "elliot_create_tool", tool)
            await call_tool_json(
                session,
                "elliot_build_connector",
                {"name": "Console Demo", "slug": CONNECTOR_SLUG, "description": "Console e2e"},
            )
            await call_tool_json(session, "elliot_export_connector", {"path": str(connector_path)})
            await call_tool_json(
                session,
                "elliot_start_runtime",
                {"port": 3001, "connector_path": str(connector_path)},
            )

    asyncio.run(_build_and_run())

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with contextlib.suppress(Exception):
            if httpx.get(f"{RUNTIME_URL}/health", timeout=2).status_code == 200:
                break
        time.sleep(0.5)

    async def _consume() -> None:
        # A single MCP connection — every call shares one Mcp-Session-Id.
        async with open_mcp_session(RUNTIME_MCP_URL) as runtime_session:
            for tool, args in _CONSUMER_CALLS:
                with contextlib.suppress(AssertionError):
                    await call_tool_json(runtime_session, tool, args)

    asyncio.run(_consume())
    return console_stack


def test_consumer_calls_group_into_one_session(consumer_session: StackEndpoints) -> None:
    """Every call from one MCP connection lands in a single grouped session."""
    sessions = httpx.get(f"{RUNTIME_URL}/v1/sessions", timeout=10).json()
    assert len(sessions) == 1, (
        f"Expected one grouped session, got {len(sessions)} — calls were not grouped"
    )
    session = sessions[0]

    # All five tool calls landed as events in the one session.
    tool_events = [e for e in session["events"] if e["type"] == "tool_call"]
    assert len(tool_events) == len(_CONSUMER_CALLS)
    assert session["total_tool_calls"] == len(_CONSUMER_CALLS)

    # Derived behaviour signals + a plain-language path summary are present.
    signal_types = {s["type"] for s in session["signals"]}
    assert "redundant" in signal_types
    assert "→" in session["summary"]


def test_sessions_stream_serves_sse_snapshot(consumer_session: StackEndpoints) -> None:
    """The /v1/sessions/stream SSE endpoint emits a snapshot frame on connect."""
    snapshot: list[dict] | None = None
    with httpx.stream("GET", f"{RUNTIME_URL}/v1/sessions/stream", timeout=10.0) as resp:
        resp.raise_for_status()
        assert resp.headers["content-type"].startswith("text/event-stream")
        event: str | None = None
        for line in resp.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and event == "snapshot":
                snapshot = json.loads(line.split(":", 1)[1].strip())
                break
    assert snapshot is not None, "SSE stream never sent a snapshot frame"
    assert len(snapshot) == 1


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not importable")
def test_agent_console_screenshot(consumer_session: StackEndpoints) -> None:
    """Render /console in Chromium, assert the session shows, and screenshot it."""
    studio_url = consumer_session.studio_url
    artifacts = Path(__file__).resolve().parent / "artifacts"
    artifacts.mkdir(exist_ok=True)
    shot = artifacts / "agent-console.png"

    with sync_playwright() as pw:  # type: ignore[union-attr]
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1366, "height": 900})
        page = context.new_page()
        try:
            page.goto(f"{studio_url}/console", wait_until="domcontentloaded", timeout=20_000)
            row = page.get_by_test_id("session-row").first
            row.wait_for(state="visible", timeout=20_000)
            row.click()  # expand to reveal the per-step trace
            page.wait_for_timeout(1_200)
            page.screenshot(path=str(shot), full_page=True)
        finally:
            context.close()
            browser.close()

    assert shot.exists() and shot.stat().st_size > 0
    print(f"\nAGENT_CONSOLE_SCREENSHOT={shot}")
