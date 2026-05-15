.PHONY: dev setup test test-cov lint format typecheck build-studio sync-skills sync-skills-check studio-open ci

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
