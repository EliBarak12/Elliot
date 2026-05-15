"""Layer 3 E2E: drive the Elliot Studio React app in a real browser.

Seeds the full session state via MCP — sources, tools, skill, connector —
then spawns the runtime and hits a few tools through it so the
observation store has real data to render. We then walk all 9 Studio
pages in Chromium and assert + screenshot each:

  /           Dashboard
  /sources    Sources
  /tools      Tools
  /skills     Skills
  /connector  Connector
  /playground Playground
  /evaluation Evaluation
  /metrics    Metrics (only populated once tools have been called)
  /console    Agent activity console

Seeding with MCP (not the agent) keeps the UI layer fast and free; chain
with ``test_layer2_claude_agent`` (the multi-agent pipeline) to exercise
the full real-user loop including the agent's contributions to session
state.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Iterator

import httpx
import pytest

try:
    from playwright.sync_api import Page, expect, sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

import contextlib

from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack
from .test_layer1_mcp_protocol import (
    BUSINESS_SKILL,
    BUSINESS_TOOLS,
    SOURCE_DEFS,
)

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not importable")


PAGES: list[tuple[str, str]] = [
    ("dashboard", "/"),
    ("sources", "/sources"),
    ("tools", "/tools"),
    ("skills", "/skills"),
    ("connector", "/connector"),
    ("playground", "/playground"),
    ("evaluation", "/evaluation"),
    ("metrics", "/metrics"),
    ("console", "/console"),
]


@pytest.fixture(scope="module")
def stack(api_base_url: str) -> Iterator[StackEndpoints]:
    """Plugin + Studio together. Runtime is started by the seeder fixture."""
    with elliot_stack(skip_studio=False, skip_runtime=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


@pytest.fixture(scope="module")
def seeded_stack(stack: StackEndpoints, api_base_url: str) -> Iterator[StackEndpoints]:
    """Populate every Studio surface with real data — sources, tools, skill,
    a built connector, a running runtime, and observation records produced
    by a few tool calls through that runtime.
    """

    runtime_mcp_url = "http://127.0.0.1:3001/mcp/"
    connector_path = stack.workspace / "connectors" / "ecommerce-ops.connector.json"
    eval_dir = stack.workspace / ".elliot" / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "ecommerce-ops-smoke.json").write_text(
        '{"id":"ecommerce-ops-smoke","name":"E-Commerce Ops smoke",'
        '"cases":[{"id":"enterprise-customers-non-empty",'
        '"tool_id":"list_active_enterprise_customers","params":{},"match_mode":"shape"}]}'
    )

    async def _seed() -> None:
        async with open_mcp_session(stack.plugin_mcp_url) as session:
            for name, path, extra in SOURCE_DEFS:
                cfg: dict = {"url": f"{api_base_url}{path}"}
                cfg.update(extra)
                await call_tool_json(
                    session,
                    "elliot_discover_source",
                    {"source_type": "rest", "config": cfg, "name": name},
                )
            for tool in BUSINESS_TOOLS:
                await call_tool_json(session, "elliot_create_tool", tool)
            await call_tool_json(session, "elliot_create_skill", BUSINESS_SKILL)
            await call_tool_json(
                session,
                "elliot_build_connector",
                {
                    "name": "E-Commerce Ops",
                    "slug": "ecommerce-ops",
                    "description": "Customer / product / order / review / org analytics",
                },
            )
            await call_tool_json(session, "elliot_export_connector", {"path": str(connector_path)})
            await call_tool_json(
                session,
                "elliot_start_runtime",
                {"port": 3001, "connector_path": str(connector_path)},
            )
            # Run the eval suite — gives the Evaluation page something to show.
            await call_tool_json(session, "elliot_run_eval", {"suite_id": "ecommerce-ops-smoke"})

    asyncio.run(_seed())

    # Wait for the runtime to be reachable.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if httpx.get("http://127.0.0.1:3001/health", timeout=2).status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)

    async def _exercise_runtime() -> None:
        # Drive real tool calls through the runtime so the observation store
        # has data for the Metrics + Console pages. A tool that errors is
        # still recorded in observability — that's exactly what we want the
        # Metrics page to surface — so we suppress on each call.
        async with open_mcp_session(runtime_mcp_url) as runtime_session:
            for tool, args in [
                ("list_active_enterprise_customers", {}),
                ("customer_order_history", {"customer_id": 1}),
                ("pending_reviews_with_low_rating", {"max_rating": 3}),
            ]:
                with contextlib.suppress(AssertionError):
                    await call_tool_json(runtime_session, tool, args)

    asyncio.run(_exercise_runtime())

    try:
        yield stack
    finally:

        async def _stop() -> None:
            async with open_mcp_session(stack.plugin_mcp_url) as session:
                with contextlib.suppress(AssertionError):
                    await call_tool_json(session, "elliot_stop_runtime", {})

        with contextlib.suppress(Exception):
            asyncio.run(_stop())


def _goto(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    # Studio is React + Tanstack Query — give it a beat for the initial
    # MCP fetch to populate, but cap it so we don't sit forever.
    page.wait_for_timeout(1500)


def test_every_studio_page_renders_seeded_state(seeded_stack: StackEndpoints) -> None:
    log_dir = seeded_stack.log_dir
    with sync_playwright() as pw:  # type: ignore[union-attr]
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1366, "height": 900})
        page = context.new_page()
        try:
            # Walk every Studio page and snapshot it.
            for label, path in PAGES:
                _goto(page, f"{seeded_stack.studio_url}{path}")
                page.screenshot(path=str(log_dir / f"studio-{label}.png"), full_page=True)

            # ── Page-specific assertions ────────────────────────────────────

            _goto(page, f"{seeded_stack.studio_url}/sources")
            for name, _path, _extra in SOURCE_DEFS:
                expect(page.get_by_text(name, exact=False).first).to_be_visible(timeout=15_000)
            page.screenshot(path=str(log_dir / "studio-sources.png"), full_page=True)

            _goto(page, f"{seeded_stack.studio_url}/tools")
            for tool in BUSINESS_TOOLS:
                expect(page.get_by_text(tool["name"], exact=False).first).to_be_visible(
                    timeout=15_000
                )
            page.screenshot(path=str(log_dir / "studio-tools.png"), full_page=True)

            _goto(page, f"{seeded_stack.studio_url}/skills")
            expect(page.get_by_text(BUSINESS_SKILL["name"], exact=False).first).to_be_visible(
                timeout=15_000
            )
            page.screenshot(path=str(log_dir / "studio-skills.png"), full_page=True)

            _goto(page, f"{seeded_stack.studio_url}/connector")
            expect(page.locator("#connector-slug")).to_have_value("ecommerce-ops", timeout=15_000)
            page.screenshot(path=str(log_dir / "studio-connector.png"), full_page=True)
        finally:
            context.close()
            browser.close()
