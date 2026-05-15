"""Tests for repo-root plugin manifests (.claude-plugin, .codex-plugin, marketplace.json).

These manifests are how Elliot is distributed to Claude Code and Codex. They
must stay valid JSON, list every shipped skill, and stay in sync with each
other.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLAUDE_SKILLS_DIR = REPO_ROOT / ".claude-plugin" / "skills"
CODEX_SKILLS_DIR = REPO_ROOT / ".codex-plugin" / "skills"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_claude_plugin_manifest_is_valid_json():
    data = _read_json(REPO_ROOT / ".claude-plugin" / "plugin.json")
    assert data["name"] == "elliot"
    assert isinstance(data["skills"], list)


def test_codex_plugin_manifest_is_valid_json():
    data = _read_json(REPO_ROOT / ".codex-plugin" / "plugin.json")
    assert data["name"] == "elliot"
    assert "mcpServers" in data
    assert "elliot" in data["mcpServers"]


def test_repo_root_marketplace_manifest_is_valid_json():
    data = _read_json(REPO_ROOT / "marketplace.json")
    assert data["name"] == "elliot"
    plugin_names = {p["name"] for p in data["plugins"]}
    assert "elliot" in plugin_names


def test_codex_marketplace_manifest_is_valid_json():
    data = _read_json(REPO_ROOT / ".codex-plugin" / "marketplace.json")
    assert data["name"] == "elliot"
    plugin_names = {p["name"] for p in data["plugins"]}
    assert "elliot" in plugin_names


def test_claude_and_codex_plugins_list_same_skills():
    claude = _read_json(REPO_ROOT / ".claude-plugin" / "plugin.json")
    codex = _read_json(REPO_ROOT / ".codex-plugin" / "plugin.json")
    assert set(claude["skills"]) == set(codex["skills"])


def test_every_listed_skill_exists_on_disk_claude():
    manifest = _read_json(REPO_ROOT / ".claude-plugin" / "plugin.json")
    for skill_rel in manifest["skills"]:
        skill_md = REPO_ROOT / ".claude-plugin" / skill_rel / "SKILL.md"
        assert skill_md.exists(), f"Missing skill file: {skill_md}"


def test_every_listed_skill_exists_on_disk_codex():
    manifest = _read_json(REPO_ROOT / ".codex-plugin" / "plugin.json")
    for skill_rel in manifest["skills"]:
        skill_md = REPO_ROOT / ".codex-plugin" / skill_rel / "SKILL.md"
        assert skill_md.exists(), f"Missing skill file: {skill_md}"


def test_codex_skills_are_in_sync_with_claude_skills():
    """sync_skills.py --check must pass — if it fails, run the sync script."""
    result = subprocess.run(
        ["python", "scripts/sync_skills.py", "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"Codex skills out of sync with Claude skills. "
        f"Run: uv run python scripts/sync_skills.py\n{result.stdout}"
    )


@pytest.mark.parametrize(
    "skill_name",
    [
        "getting-started",
        "discover-source",
        "build-connector",
        "lint-connector",
        "run-eval",
        "deploy",
    ],
)
def test_each_skill_has_frontmatter_and_body(skill_name: str):
    skill_md = CLAUDE_SKILLS_DIR / skill_name / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{skill_name} missing frontmatter delim"
    # Confirm frontmatter terminates and there's a body
    lines = text.splitlines()
    assert lines.index("---", 1) > 1
    body_start = lines.index("---", 1) + 1
    body = "\n".join(lines[body_start:]).strip()
    assert len(body) > 50, f"{skill_name} body too short: {len(body)}"
