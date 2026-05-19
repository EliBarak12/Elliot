"""Tests for plugin manifests (.claude-plugin, .codex-plugin).

These manifests determine whether the marketplace install actually works:

  /plugin marketplace add EliBarak12/Elliot
  /plugin install elliot@elliot

We assert against the Claude Code and Codex plugin specs:
- marketplace.json lives at .claude-plugin/marketplace.json (Claude Code) and
  .agents/plugins/marketplace.json (Codex) — NOT inside .codex-plugin/
- marketplace.json requires `name` and `plugins`; Claude Code also `owner.name`
- Each plugin entry requires `name` and `source`
- `source` is either a relative path starting with `./` or a structured object
- plugin.json fields: `name` required; MCP config via `mcpServers` or an
  auto-discovered `.mcp.json` at the plugin root
- Skills live under `skills/<name>/SKILL.md` at the PLUGIN ROOT (a sibling of
  .claude-plugin/ and .codex-plugin/) — never inside .claude-plugin/skills/
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
EXPECTED_SKILLS = (
    "getting-started",
    "discover-source",
    "build-connector",
    "lint-connector",
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
            assert src.get("source") in {"github", "url", "git-subdir", "local", "npm"}, (
                f"Object source must declare a known type (got: {src})"
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


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_each_skill_dir_exists_at_plugin_root(skill_name: str):
    """Claude Code and Codex auto-discover skills under <plugin-root>/skills/
    <name>/SKILL.md — the `skills/` directory sits NEXT TO .claude-plugin/, not
    inside it.
    """
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    assert skill_md.exists(), f"Missing skill file: {skill_md}"


def test_skills_are_not_nested_inside_claude_plugin():
    """Regression guard: skills inside .claude-plugin/skills/ are NEVER loaded
    by Claude Code — only the MCP server would attach. Skills must live at the
    plugin root.
    """
    nested = REPO_ROOT / ".claude-plugin" / "skills"
    assert not nested.exists(), (
        "Found .claude-plugin/skills/. Claude Code auto-discovers skills from "
        "<plugin-root>/skills/, NOT from inside .claude-plugin/. Move them to "
        "the repo-root skills/ directory."
    )


def test_codex_plugin_manifest_is_valid():
    """Codex manifest: name + mcpServers, and `skills` pointing at ./skills/."""
    data = _read_json(REPO_ROOT / ".codex-plugin" / "plugin.json")
    assert data["name"] == "elliot"
    assert "mcpServers" in data
    assert "elliot" in data["mcpServers"]
    # Codex resolves `skills` relative to the plugin root; the path must exist.
    skills_ref = data.get("skills")
    assert skills_ref, "Codex plugin.json must declare a `skills` path"
    resolved = (REPO_ROOT / skills_ref.lstrip("./")).resolve()
    assert resolved.is_dir(), f"Codex `skills` path does not resolve: {skills_ref}"


def test_codex_marketplace_is_at_agents_plugins_path():
    """Codex reads marketplaces from .agents/plugins/marketplace.json."""
    path = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
    assert path.exists(), (
        "Codex marketplace missing. Codex discovers .agents/plugins/"
        "marketplace.json — a file under .codex-plugin/ is NOT discovered."
    )
    data = _read_json(path)
    assert data["name"] == "elliot"
    plugin_names = {p["name"] for p in data["plugins"]}
    assert "elliot" in plugin_names


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
