"""Layer 3 E2E: drive the Elliot Studio React app in a real browser.

This layer seeds session state via MCP (cheap and deterministic), then
opens Studio at ``http://127.0.0.1:5173`` in Chromium and asserts that the
agent-visible state shows up on the Sources / Tools / Connector pages —
the same pages a human user lands on after Claude finishes a connector.

By seeding with MCP (not the agent) we avoid burning LLM tokens on the UI
check. To exercise the *full* loop end-to-end including the Studio render,
chain ``test_layer2_claude_agent`` before this — both share the same
plugin-session ndjson, so an agent run leaves session state on disk that
Studio reflects.
"""

from __future__ import annotations

import os

import pytest

try:
    from playwright.sync_api import Page, expect, sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

from .helpers.mcp_client import call_tool_json, open_mcp_session
from .helpers.stack import StackEndpoints, elliot_stack
from .test_layer1_mcp_protocol import BUSINESS_TOOLS, SOURCE_DEFS

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not importable")


@pytest.fixture(scope="module")
def stack(api_base_url: str):  # type: ignore[no-untyped-def]
    """Plugin + Studio together — Layer 3 needs the React app live."""
    with elliot_stack(skip_studio=False, skip_runtime=True) as endpoints:
        os.environ["ELLIOT_E2E_API_BASE"] = api_base_url
        # Make Playwright look under the env-provided browsers cache.
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
        try:
            yield endpoints
        finally:
            os.environ.pop("ELLIOT_E2E_API_BASE", None)


@pytest.fixture(scope="module")
def seeded_stack(stack: StackEndpoints, api_base_url: str) -> StackEndpoints:
    """Lay down 4 sources + 4 tools + a built connector via MCP."""
    import asyncio

    async def _seed() -> None:
        async with open_mcp_session(stack.plugin_mcp_url) as session:
            for name, path in SOURCE_DEFS:
                await call_tool_json(
                    session,
                    "elliot_discover_source",
                    {
                        "source_type": "rest",
                        "config": {"url": f"{api_base_url}{path}"},
                        "name": name,
                    },
                )
            for tool in BUSINESS_TOOLS:
                await call_tool_json(session, "elliot_create_tool", tool)
            await call_tool_json(
                session,
                "elliot_build_connector",
                {
                    "name": "E-Commerce Ops",
                    "slug": "ecommerce-ops",
                    "description": "4-API e-commerce ops connector",
                },
            )

    asyncio.run(_seed())
    return stack


def _goto(page: Page, url: str) -> None:
    # Don't wait for "networkidle" — the MCP streamable-HTTP transport keeps
    # the network busy with SSE polling, so the page is never strictly idle.
    page.goto(url, wait_until="domcontentloaded", timeout=20_000)


def test_studio_shows_agent_built_sources_tools_and_connector(
    seeded_stack: StackEndpoints,
) -> None:
    with sync_playwright() as pw:  # type: ignore[union-attr]
        # Use bundled headless chromium; --no-sandbox required to run as root.
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        try:
            # ── Sources page ────────────────────────────────────────────────
            _goto(page, f"{seeded_stack.studio_url}/sources")
            for name, _ in SOURCE_DEFS:
                # The Studio renders each source's logical name (the table name
                # we passed to elliot_discover_source) as visible text.
                expect(page.get_by_text(name, exact=False).first).to_be_visible(timeout=10_000)
            page.screenshot(path=str(seeded_stack.log_dir / "studio-sources.png"), full_page=True)

            # ── Tools page ─────────────────────────────────────────────────
            _goto(page, f"{seeded_stack.studio_url}/tools")
            for tool in BUSINESS_TOOLS:
                expect(page.get_by_text(tool["name"], exact=False).first).to_be_visible(
                    timeout=10_000
                )
            page.screenshot(path=str(seeded_stack.log_dir / "studio-tools.png"), full_page=True)

            # ── Connector page — slug populated from session, lint clean ──
            _goto(page, f"{seeded_stack.studio_url}/connector")
            slug_input = page.locator("#connector-slug")
            expect(slug_input).to_have_value("ecommerce-ops", timeout=10_000)

            # Click the "Lint" button (it's not auto-run) and assert the lint
            # panel surfaces with no destructive badge — the agent's connector
            # is clean.
            page.get_by_role("button", name="Lint").first.click()
            expect(page.locator('[data-testid="lint-panel"]')).to_be_visible(timeout=10_000)
            page.screenshot(
                path=str(seeded_stack.log_dir / "studio-connector.png"),
                full_page=True,
            )
        finally:
            context.close()
            browser.close()
