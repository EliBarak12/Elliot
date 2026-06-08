"""Capture real Studio UI screenshots showing what an agent built.

Boots the full stack (plugin + runtime + Studio), seeds a connector via MCP,
deploys it, has two consumer agents call its tools (so Metrics/Console have
data), then drives Studio in Chromium and writes a screenshot of every page to
``dev/e2e/launch_gateway/screenshots/``. This is the visual proof that the UI
surfaces everything an agent builds and does.

Run:  uv run python dev/e2e/launch_gateway/studio_screenshots.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[3]))

from dev.e2e.helpers.mcp_client import call_tool_json, open_mcp_session  # noqa: E402
from dev.e2e.helpers.mock_apis import MockAPIServer  # noqa: E402
from dev.e2e.helpers.stack import elliot_stack  # noqa: E402
from dev.e2e.test_layer1_mcp_protocol import (  # noqa: E402
    BUSINESS_SKILL,
    BUSINESS_TOOLS,
    SOURCE_DEFS,
)

OUT = HERE.parent / "screenshots"
PAGES = [
    ("dashboard", "/"),
    ("sources", "/sources"),
    ("tools", "/tools"),
    ("skills", "/skills"),
    ("connector", "/connector"),
    ("metrics", "/metrics"),
    ("console", "/console"),
]


async def seed(plugin_mcp: str, api_base: str, connector_path: Path) -> None:
    async with open_mcp_session(plugin_mcp) as s:
        for name, path, extra in SOURCE_DEFS:
            cfg = {"url": f"{api_base}{path}"}
            cfg.update(extra)
            await call_tool_json(
                s, "elliot_discover_source", {"source_type": "rest", "config": cfg, "name": name}
            )
        for tool in BUSINESS_TOOLS:
            await call_tool_json(s, "elliot_create_tool", tool)
        await call_tool_json(s, "elliot_create_skill", BUSINESS_SKILL)
        await call_tool_json(
            s,
            "elliot_build_connector",
            {
                "name": "E-Commerce Ops",
                "slug": "ecommerce-ops",
                "description": "Customer / product / order / review analytics",
            },
        )
        await call_tool_json(s, "elliot_export_connector", {"path": str(connector_path)})
        await call_tool_json(
            s, "elliot_start_runtime", {"port": 3001, "connector_path": str(connector_path)}
        )


async def exercise(runtime_mcp: str) -> None:
    scenarios = [
        [
            ("list_active_enterprise_customers", {}),
            ("top_products_by_revenue", {"limit": 3}),
            ("top_products_by_revenue", {"limit": 5}),
        ],
        [
            ("customer_order_history", {"customer_id": 1}),
            ("pending_reviews_with_low_rating", {"max_rating": 3}),
            ("customer_order_history", {"customer_id": -999}),
        ],  # one bad call for contrast
    ]
    for calls in scenarios:
        async with open_mcp_session(runtime_mcp) as rs:
            for tool, args in calls:
                with contextlib.suppress(AssertionError):
                    await call_tool_json(rs, tool, args)
        await asyncio.sleep(0.4)


def shoot(studio_url: str) -> list[Path]:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for label, path in PAGES:
            page.goto(f"{studio_url}{path}", wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(2000)  # let React Query populate
            dest = OUT / f"studio-{label}.png"
            page.screenshot(path=str(dest), full_page=True)
            saved.append(dest)
            print(f"   captured {dest.name}", flush=True)
        browser.close()
    return saved


def main() -> int:
    mock = MockAPIServer(port=8181)
    mock.start()
    try:
        with elliot_stack(skip_studio=False, skip_runtime=True) as stack:
            os.environ["ELLIOT_E2E_API_BASE"] = mock.base_url
            connector_path = stack.workspace / "connectors" / "ecommerce-ops.connector.json"
            asyncio.run(seed(stack.plugin_mcp_url, mock.base_url, connector_path))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                with contextlib.suppress(Exception):
                    if httpx.get("http://127.0.0.1:3001/health", timeout=2).status_code == 200:
                        break
                time.sleep(0.5)
            asyncio.run(exercise("http://127.0.0.1:3001/mcp/"))
            print("Capturing Studio screenshots...", flush=True)
            saved = shoot(stack.studio_url)
            with contextlib.suppress(Exception):
                asyncio.run(_stop(stack.plugin_mcp_url))
            print(f"\nSaved {len(saved)} screenshots to {OUT}")
    finally:
        mock.stop()
    return 0


async def _stop(plugin_mcp: str) -> None:
    async with open_mcp_session(plugin_mcp) as s:
        with contextlib.suppress(AssertionError):
            await call_tool_json(s, "elliot_stop_runtime", {})


if __name__ == "__main__":
    raise SystemExit(main())
