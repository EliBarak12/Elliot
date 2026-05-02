# 002 — Python Project Config

**Sprint**: 1 | **Estimate**: 1h | **Depends on**: 001

## Objective
Shared pytest configuration, mypy strict type checking, and asyncio mode settings.

## Files to Create / Modify

### Add to root `pyproject.toml`
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["packages"]
python_files = "test_*.py"
python_functions = "test_*"
addopts = "--tb=short -q"

[tool.mypy]
python_version = "3.12"
strict = true
warn_return_any = true
warn_unused_ignores = true
exclude = ["dist/", ".venv/", "packages/studio/"]

[[tool.mypy.overrides]]
module = ["jmespath.*", "respx.*"]
ignore_missing_imports = true
```

### `pytest.ini` (alternative if pyproject.toml conflicts)
Leave empty — config lives in `pyproject.toml`.

## Done When
- [ ] `uv run pytest` exits 0 with "no tests ran" (not an error)
- [ ] `uv run mypy packages/core/src` exits 0 on empty `__init__.py`
- [ ] `asyncio_mode = auto` means `async def test_*` works without `@pytest.mark.asyncio`
