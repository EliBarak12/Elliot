# 003 — Ruff Linter + Formatter

**Sprint**: 1 | **Estimate**: 30min | **Depends on**: 002

## Objective
Fast Python linter and formatter (replaces ESLint + Prettier for the Python side).

## Files to Create / Modify

### Add to root `pyproject.toml`
```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "ANN"]
ignore = ["ANN101", "ANN102"]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["ANN"]

[tool.ruff.format]
quote-style = "double"
```

## Done When
- [ ] `uv run ruff check .` exits 0 on empty package stubs
- [ ] `uv run ruff format --check .` exits 0
- [ ] `make lint` works via Makefile
