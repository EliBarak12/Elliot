.PHONY: dev setup run stop test test-cov lint format typecheck build-studio studio-open ci e2e e2e-mcp e2e-agent e2e-ui

dev:
	uv run elliot connect
	uv run python scripts/open_studio.py &
	honcho start

# Run Elliot from pre-built images — no Python/Node toolchain needed, only
# Docker. Studio is served at http://localhost:8080.
run:
	docker compose -f docker-compose.run.yml pull
	docker compose -f docker-compose.run.yml up -d
	@echo "Elliot is running — Studio: http://localhost:8080"

stop:
	docker compose -f docker-compose.run.yml down

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
# runs the canonical workflow over MCP-over-HTTP (Layer 1, free), drives a
# three-agent pipeline against the live plugin (Layer 2 — builder + consumer +
# reviewer, costs API tokens), and walks all 9 Studio pages in Chromium
# (Layer 3, free). Not part of the pre-push mandatory suite; opt-in via these
# targets.
e2e:
	PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
	uv run pytest dev/e2e -v --tb=short

e2e-mcp:
	uv run pytest dev/e2e/test_layer1_mcp_protocol.py -v --tb=short

# Builder → Consumer → Reviewer multi-agent pipeline. Set budget knobs via
# ELLIOT_E2E_BUILDER_BUDGET_USD / ELLIOT_E2E_CONSUMER_BUDGET_USD /
# ELLIOT_E2E_REVIEWER_BUDGET_USD if you want tighter / looser caps.
e2e-agent:
	uv run pytest dev/e2e/test_layer2_claude_agent.py -v --tb=short

e2e-ui:
	PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
	uv run pytest dev/e2e/test_layer3_studio_ui.py -v --tb=short

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy packages/core/src packages/mcp-plugin/src packages/connector-runtime/src

build-studio:
	pnpm --filter @elliot/studio run build

ci: lint typecheck test-cov
	@echo "All checks passed."
