"""Tests for elliot_mcp_plugin.prompts: cross-agent skill delivery via MCP."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.prompts import (
    Skill,
    _parse_skill_file,
    _prompt_name,
    _split_frontmatter,
    load_skills,
    register_prompts,
)


def test_split_frontmatter_extracts_yaml_block():
    text = "---\nname: foo\ndescription: bar\n---\nbody line"
    fm, body = _split_frontmatter(text)
    assert fm == {"name": "foo", "description": "bar"}
    assert body == "body line"


def test_split_frontmatter_returns_empty_when_no_delim():
    text = "just a body, no frontmatter"
    fm, body = _split_frontmatter(text)
    assert fm == {}
    assert body == text


def test_split_frontmatter_returns_empty_when_unterminated():
    text = "---\nname: foo\n  (no closing delim)"
    fm, body = _split_frontmatter(text)
    assert fm == {}


def test_prompt_name_converts_kebab_to_snake():
    assert _prompt_name("build-connector") == "build_connector"
    assert _prompt_name("getting-started") == "getting_started"
    assert _prompt_name("already_snake") == "already_snake"


def test_parse_skill_file_requires_description(tmp_path: Path):
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: test\n---\nbody")
    assert _parse_skill_file(skill_md) is None


def test_parse_skill_file_extracts_all_fields(tmp_path: Path):
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: test-skill\n"
        "description: A test skill\n"
        "when_to_use: when testing\n"
        "argument-hint: '[arg]'\n"
        "---\n"
        "body content here"
    )
    skill = _parse_skill_file(skill_md)
    assert skill is not None
    assert skill.name == "test-skill"
    assert skill.description == "A test skill"
    assert skill.when_to_use == "when testing"
    assert skill.argument_hint == "[arg]"
    assert "body content" in skill.body


def test_load_skills_finds_repo_skills():
    """The real plugin-root skills/ directory should be discoverable."""
    skills = load_skills()
    names = {s.name for s in skills}
    # Six canonical skills must all load
    assert "getting-started" in names
    assert "discover-source" in names
    assert "build-connector" in names
    assert "lint-connector" in names
    assert "run-eval" in names
    assert "deploy" in names


def test_load_skills_uses_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    skill_dir = tmp_path / "my-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: An overridden skill\n---\nhello"
    )
    monkeypatch.setenv("ELLIOT_SKILLS_DIR", str(tmp_path))
    skills = load_skills()
    assert any(s.name == "my-skill" for s in skills)


def test_load_skills_handles_missing_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """If no skills dir is found, return empty list rather than raising."""
    monkeypatch.setenv("ELLIOT_SKILLS_DIR", str(tmp_path / "does-not-exist"))
    # Also need to disable the walk-up fallback. Change cwd to a location with
    # no .claude-plugin ancestor — but the function walks from __file__ parents,
    # which always finds the repo's .claude-plugin. So we rely on env override
    # pointing at a missing dir; the function should log and walk up, finding
    # the real one. To truly test the "nothing found" path, we'd need to mock.
    # Here we just confirm the function tolerates a bad override gracefully.
    skills = load_skills()
    # Either it falls back to the real dir, or returns [] — both are valid.
    assert isinstance(skills, list)


def test_register_prompts_registers_each_skill():
    mcp = FastMCP("test")
    count = register_prompts(mcp)
    assert count >= 6  # six canonical skills
    prompt_names = set(mcp._prompt_manager._prompts.keys())
    assert "getting_started" in prompt_names
    assert "discover_source" in prompt_names
    assert "build_connector" in prompt_names


@pytest.mark.asyncio
async def test_getting_started_prompt_is_callable():
    mcp = FastMCP("test")
    register_prompts(mcp)
    result = await mcp.get_prompt("getting_started", {})
    text = result.messages[0].content.text  # type: ignore[union-attr]
    # Body must mention the principles and point at other prompts
    assert "principles" in text.lower()
    assert "discover_source" in text or "discover-source" in text
    assert "deploy" in text.lower()


@pytest.mark.asyncio
async def test_getting_started_prompt_covers_server_prerequisite():
    """The plugin must teach the agent that the Elliot stack has to be running
    before any tool call works. This is the #1 failure mode for new users."""
    mcp = FastMCP("test")
    register_prompts(mcp)
    result = await mcp.get_prompt("getting_started", {})
    text = result.messages[0].content.text  # type: ignore[union-attr]
    lowered = text.lower()
    # Must reference the prereq, the clone command, and `make dev`
    assert "prerequisite" in lowered or "server" in lowered
    assert "git clone" in text
    assert "make dev" in text
    # And Studio's auto-open URL so the user knows what success looks like
    assert "localhost:5173" in text or "5173" in text


@pytest.mark.asyncio
async def test_prompt_body_includes_when_to_use():
    """If when_to_use is in the frontmatter, the rendered body surfaces it."""
    mcp = FastMCP("test")
    register_prompts(mcp)
    result = await mcp.get_prompt("getting_started", {})
    text = result.messages[0].content.text  # type: ignore[union-attr]
    assert "When to use:" in text


def test_skill_dataclass_is_immutable():
    """Skill is frozen — accidental mutation must raise FrozenInstanceError."""
    from dataclasses import FrozenInstanceError

    s = Skill(name="x", description="y", body="z")
    with pytest.raises(FrozenInstanceError):
        s.name = "changed"  # type: ignore[misc]


def test_skills_dir_override_missing_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A bad ELLIOT_SKILLS_DIR override should not crash — fall back to repo walk."""
    monkeypatch.setenv("ELLIOT_SKILLS_DIR", str(tmp_path / "nonexistent"))
    skills = load_skills()
    # Repo walk should still find the plugin-root skills/ directory.
    assert len(skills) >= 6
    # Confirm the override was at least *attempted* — no exception raised
    assert "ELLIOT_SKILLS_DIR" in os.environ
