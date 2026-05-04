.PHONY: dev setup test test-cov lint format typecheck build-studio ci

dev:
	honcho start

setup:
	uv sync
	pnpm install

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

ci: lint typecheck test-cov
	@echo "All checks passed."
