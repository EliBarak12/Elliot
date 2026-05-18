"""Tests for plugin manifests (.claude-plugin, .codex-plugin, .cursor-plugin).

These manifests determine whether the marketplace install actually works:

  /plugin marketplace add EliBarak12/elliot
  /plugin install elliot@elliot

We assert against the Claude Code plugin spec (docs.claude.com):
- marketplace.json lives at .claude-plugin/marketplace.json (NOT the repo root)
- marketplace.json requires `name`, `owner.name`, `plugins`
- Each plugin entry requires `name` and `source`
- `source` is either a relative path starting with `./` or a structured object
- plugin.json fields: `name` required; MCP config goes via `mcpServers` or
  auto-discovered `.mcp.json` at the plugin root
- Skills live under `skills/<name>/SKILL.md` and are auto-discovered
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
EXPECTED_SKILLS = (
    "getting-started",
    "onboard-product",
    "discover-source",
    "build-connector",
    "lint-connector",
    "audit-connector",
    "run-eval",
    "deploy",
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_marketplace_manifest_is_at_claude_plugin_path():
    """Spec: marketplace.json MUST be at .claude-plugin/marketplace.json."""
    path = REPO_ROOT / ".claude-plugin" / "marketplace.json"
    assert path.exists(), (
        "Marketplace file missing at the spec-required path. Claude Code looks "
        "for .claude-plugin/marketplace.json — a marketplace.json at the repo "
        "root is NOT discovered."
    )


def test_no_stale_marketplace_json_at_repo_root():
    """A leftover /marketplace.json would confuse contributors — keep one source of truth."""
    legacy = REPO_ROOT / "marketplace.json"
    assert not legacy.exists(), (
        "Stale /marketplace.json found at repo root. The canonical location is "
        ".claude-plugin/marketplace.json — remove the legacy file."
    )


def test_marketplace_required_fields():
    data = _read_json(REPO_ROOT / ".claude-plugin" / "marketplace.json")
    assert data["name"] == "elliot"
    assert "owner" in data, "marketplace.json missing required 'owner' field"
    assert data["owner"].get("name"), "owner.name is required"
    assert isinstance(data["plugins"], list)
    assert len(data["plugins"]) >= 1


def test_marketplace_plugin_entry_has_valid_source():
    """source: relative path starting with `./` OR a {source: github|url|npm} object."""
    data = _read_json(REPO_ROOT / ".claude-plugin" / "marketplace.json")
    for entry in data["plugins"]:
        assert "name" in entry
        assert "source" in entry
        src = entry["source"]
        if isinstance(src, str):
            assert src.startswith("./"), f"Relative path source must start with './' (got: {src!r})"
        elif isinstance(src, dict):
            assert src.get("source") in {"github", "url", "git-subdir", "npm"}, (
                f"Object source must declare type github|url|git-subdir|npm (got: {src})"
            )
        else:
            raise AssertionError(f"source must be string or object (got: {type(src)})")


def test_claude_plugin_manifest_has_required_fields():
    """plugin.json: only `name` is strictly required by the spec."""
    data = _read_json(REPO_ROOT / ".claude-plugin" / "plugin.json")
    assert data["name"] == "elliot"
    # Forbidden: the `mcp` field doesn't exist in the spec — it's `mcpServers`
    assert "mcp" not in data, (
        "plugin.json uses the wrong key 'mcp'. The spec field is 'mcpServers' "
        "or auto-discovery of .mcp.json at the plugin root."
    )
    # Forbidden: `..` paths in any field
    for v in data.values():
        if isinstance(v, str):
            assert ".." not in v, (
                f"plugin.json fields cannot use '..' (got: {v!r}); plugins can't "
                "reference files outside their directory."
            )
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    assert ".." not in item


def test_plugin_mcp_config_is_auto_discoverable():
    """With no explicit `mcpServers` in plugin.json, Claude Code looks for
    .mcp.json at the plugin root. The plugin root IS the directory containing
    .claude-plugin/, so for this repo that's the repo root.
    """
    plugin_mcp = REPO_ROOT / ".mcp.json"
    assert plugin_mcp.exists(), "Plugin .mcp.json must exist at the plugin root"
    data = _read_json(plugin_mcp)
    assert "mcpServers" in data
    assert "elliot" in data["mcpServers"]


def test_skills_are_at_plugin_root_not_inside_claude_plugin():
    """Spec: component dirs (skills/, agents/, ...) must live at the plugin
    root, NOT inside .claude-plugin/. The plugin root is the repo root.
    """
    assert SKILLS_DIR.is_dir(), "skills/ must exist at the repo (plugin) root"
    stray = REPO_ROOT / ".claude-plugin" / "skills"
    assert not stray.exists(), (
        "skills/ must not live inside .claude-plugin/ — Claude Code only "
        "auto-discovers component dirs at the plugin root."
    )


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_each_skill_dir_exists_for_auto_discovery(skill_name: str):
    """Claude Code auto-discovers skills under skills/<name>/SKILL.md — no
    manifest declaration needed.
    """
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    assert skill_md.exists(), f"Missing skill file: {skill_md}"


def test_codex_plugin_manifest_is_valid_json():
    """Codex plugin format (Mar 2026) is experimental in this repo — we still
    keep the file valid JSON and mirror the same skill set."""
    data = _read_json(REPO_ROOT / ".codex-plugin" / "plugin.json")
    assert data["name"] == "elliot"
    assert "mcpServers" in data
    assert "elliot" in data["mcpServers"]


def test_codex_marketplace_manifest_is_valid_json():
    data = _read_json(REPO_ROOT / ".codex-plugin" / "marketplace.json")
    assert data["name"] == "elliot"
    plugin_names = {p["name"] for p in data["plugins"]}
    assert "elliot" in plugin_names


def test_codex_plugin_skills_resolve_to_repo_root():
    """Codex plugin.json lists skills by path relative to the plugin root.
    The plugin root is the repo root, so each `skills/<name>` must exist there.
    """
    data = _read_json(REPO_ROOT / ".codex-plugin" / "plugin.json")
    for rel in data.get("skills", []):
        assert (REPO_ROOT / rel).is_dir(), f"Codex skill path does not exist: {rel}"


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_each_skill_has_frontmatter_and_body(skill_name: str):
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{skill_name} missing frontmatter delim"
    lines = text.splitlines()
    assert lines.index("---", 1) > 1
    body_start = lines.index("---", 1) + 1
    body = "\n".join(lines[body_start:]).strip()
    assert len(body) > 50, f"{skill_name} body too short: {len(body)}"
