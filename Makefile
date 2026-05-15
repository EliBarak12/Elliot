.PHONY: dev setup test test-cov lint format typecheck build-studio sync-skills sync-skills-check studio-open ci e2e e2e-mcp e2e-agent e2e-ui

dev:
	uv run python scripts/sync_skills.py
	uv run elliot connect
	uv run python scripts/open_studio.py &
	honcho start

studio-open:
	uv run python scripts/open_studio.py

setup:
	uv sync
	pnpm install
	uv run elliot connect

test:
	uv run pytest --tb=short

test-cov:
	uv run pytest --tb=short --cov --cov-report=term-missing

# Real-user end-to-end suite. Boots plugin/runtime/studio in a temp workspace,
# runs the canonical workflow over MCP-over-HTTP (Layer 1), drives a headless
# Claude Code agent against the live plugin (Layer 2 — costs API tokens), and
# verifies the resulting state in Studio via Playwright (Layer 3). Not part
# of the pre-push mandatory suite; opt-in via these targets.
e2e:
	PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
	uv run pytest tests/e2e -v --tb=short

e2e-mcp:
	uv run pytest tests/e2e/test_layer1_mcp_protocol.py -v --tb=short

e2e-agent:
	uv run pytest tests/e2e/test_layer2_claude_agent.py -v --tb=short

e2e-ui:
	PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
	uv run pytest tests/e2e/test_layer3_studio_ui.py -v --tb=short

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src

build-studio:
	pnpm --filter @elliot/studio run build

sync-skills:
	uv run python scripts/sync_skills.py

sync-skills-check:
	uv run python scripts/sync_skills.py --check

ci: lint typecheck test-cov sync-skills-check
	@echo "All checks passed."
