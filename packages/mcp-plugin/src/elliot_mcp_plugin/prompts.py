"""MCP prompts: ship Elliot skills to every agent over the wire.

Claude Code reads SKILL.md files from `.claude-plugin/skills/` directly, but
Codex / Cursor / Windsurf / VS Code Copilot have no equivalent loader — they
only see what the MCP server exposes. Registering each skill as an MCP prompt
delivers the same workflow guidance to every agent that speaks MCP.

Source of truth: `.claude-plugin/skills/<name>/SKILL.md` at the repo root.
Each file has YAML frontmatter and a markdown body; the body becomes the
prompt content, the frontmatter becomes the prompt name + description.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import structlog
import yaml
from mcp.server.fastmcp import FastMCP

log = structlog.get_logger(__name__)

_FRONTMATTER_DELIM = "---"


@dataclass(frozen=True)
class Skill:
    """A parsed SKILL.md: frontmatter metadata + markdown body."""

    name: str
    description: str
    body: str
    when_to_use: str | None = None
    argument_hint: str | None = None


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, body). If no frontmatter, returns ({}, text)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        return {}, text
    try:
        end = lines.index(_FRONTMATTER_DELIM, 1)
    except ValueError:
        return {}, text
    raw = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    parsed = yaml.safe_load(raw) or {}
    if not isinstance(parsed, dict):
        return {}, text
    # Coerce to str — YAML may parse numbers; we only ever expect strings here.
    return {str(k): str(v) for k, v in parsed.items()}, body


def _parse_skill_file(path: Path) -> Skill | None:
    """Parse a single SKILL.md. Returns None if required fields are missing."""
    text = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)
    name = fm.get("name") or path.parent.name
    description = fm.get("description")
    if not description:
        log.warning("prompts.skill.missing_description", path=str(path))
        return None
    return Skill(
        name=name,
        description=description,
        body=body,
        when_to_use=fm.get("when_to_use"),
        argument_hint=fm.get("argument-hint") or fm.get("argument_hint"),
    )


def _find_skills_dir() -> Path | None:
    """Locate `.claude-plugin/skills/`.

    Order:
      1. ELLIOT_SKILLS_DIR env var override (deployable image / packaged install)
      2. Repo-root layout: walk up from this file looking for `.claude-plugin/skills`
    """
    override = os.environ.get("ELLIOT_SKILLS_DIR")
    if override:
        p = Path(override)
        if p.is_dir():
            return p
        log.warning("prompts.skills_dir.override_missing", path=override)

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / ".claude-plugin" / "skills"
        if candidate.is_dir():
            return candidate
    return None


def load_skills() -> list[Skill]:
    """Read every SKILL.md from the skills directory. Empty list if none found."""
    skills_dir = _find_skills_dir()
    if skills_dir is None:
        log.warning("prompts.skills_dir.not_found")
        return []
    out: list[Skill] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        parsed = _parse_skill_file(skill_md)
        if parsed is not None:
            out.append(parsed)
    log.info("prompts.skills.loaded", count=len(out), dir=str(skills_dir))
    return out


def _prompt_name(skill_name: str) -> str:
    """MCP prompt names cannot contain `-`. SKILL.md uses kebab-case; convert."""
    return skill_name.replace("-", "_")


def _render_prompt_body(skill: Skill) -> str:
    """Wrap the skill body with a header that mentions when_to_use, if present."""
    header_parts: list[str] = [f"# Elliot skill: {skill.name}", ""]
    if skill.when_to_use:
        header_parts.extend([f"_When to use:_ {skill.when_to_use}", ""])
    return "\n".join(header_parts) + skill.body


def register_prompts(mcp: FastMCP) -> int:
    """Register every skill in `.claude-plugin/skills/` as an MCP prompt.

    Returns the number of prompts registered.
    """
    skills = load_skills()
    for skill in skills:
        prompt_name = _prompt_name(skill.name)
        rendered = _render_prompt_body(skill)

        def make_fn(body: str) -> Callable[[], str]:
            def _fn() -> str:
                return body

            return _fn

        fn = make_fn(rendered)
        # FastMCP also uses fn.__doc__ as a description fallback. We pass the
        # description explicitly below, so this is just future-proofing.
        fn.__doc__ = skill.description
        mcp.prompt(name=prompt_name, description=skill.description)(fn)
        log.info("prompts.registered", name=prompt_name)
    return len(skills)
