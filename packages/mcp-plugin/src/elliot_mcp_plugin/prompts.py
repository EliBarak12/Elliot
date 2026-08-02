"""MCP prompts: ship Elliot skills to every agent over the wire.

Claude Code and Codex auto-discover SKILL.md files from the plugin root's
`skills/` directory, but agents reached only over MCP (and older clients)
have no equivalent loader — they only see what the MCP server exposes.
Registering each skill as an MCP prompt delivers the same workflow guidance
to every agent that speaks MCP.

Source of truth: `skills/<name>/SKILL.md` at the plugin root (the repo root,
the directory that contains `.claude-plugin/` and `.codex-plugin/`). Each
file has YAML frontmatter and a markdown body; the body becomes the prompt
content, the frontmatter becomes the prompt name + description.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog
import yaml

from elliot_core.mcp_compat import FastMCP

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
    """Locate the `skills/` directory.

    Order:
      1. ELLIOT_SKILLS_DIR env var override (deployable image / packaged install)
      2. Repo-root layout: walk up from this file looking for a `skills/`
         directory that sits next to `.claude-plugin/` (the plugin root) — this
         is the editable-install / source-checkout path.
      3. Bundled-in-wheel fallback: ``elliot_mcp_plugin/_bundled_skills``. The
         repo-root `skills/` is force-included into the wheel at build time (see
         the package's pyproject), so when the plugin is installed from a git
         subdirectory — as Elliot Cloud installs it — the skills travel with the
         package even though they live outside ``src/`` in the repo. Without this
         the cloud builder served an empty ``prompts/list`` (no skills, no
         ``getting_started``).
    """
    override = os.environ.get("ELLIOT_SKILLS_DIR")
    if override:
        p = Path(override)
        if p.is_dir():
            return p
        log.warning("prompts.skills_dir.override_missing", path=override)

    here = Path(__file__).resolve()
    for parent in here.parents:
        # Anchor on the plugin root: the directory holding `.claude-plugin/`.
        # Skills live in a sibling `skills/`, not inside `.claude-plugin/`.
        if (parent / ".claude-plugin").is_dir():
            candidate = parent / "skills"
            if candidate.is_dir():
                return candidate

    bundled = here.parent / "_bundled_skills"
    if bundled.is_dir():
        return bundled
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


def _make_body_fn(body: str) -> Callable[[], str]:
    def _fn() -> str:
        return body

    return _fn


def _session_skill_prompt_name(skill_id: str) -> str:
    return _prompt_name(f"skill_{skill_id}")


def register_session_skill_prompt(mcp: FastMCP, skill: Any) -> str:
    """Register one session-created skill (a SkillDefinition) as an MCP prompt.

    Without this, skills built via ``elliot_create_skill`` lived only in the
    session file — ``prompts/list`` never showed them, so agents couldn't
    invoke them over MCP. The rendered prompt describes the steps and points
    at ``elliot_preview_skill`` for end-to-end execution. Returns the prompt
    name. Re-registering the same skill simply overwrites it.
    """
    name = _session_skill_prompt_name(skill.id)
    inputs = ", ".join(p.name for p in skill.input_parameters) or "(none)"
    when_to_use = getattr(skill, "when_to_use", "") or ""
    instructions = getattr(skill, "instructions", "") or ""

    parts = [f"# Elliot skill: {skill.name}", "", skill.description, ""]
    if when_to_use.strip():
        parts += [f"_When to use:_ {when_to_use.strip()}", ""]
    parts += [f"Inputs: {inputs}", ""]
    if instructions.strip():
        parts += [instructions.strip(), ""]
    if skill.steps:
        steps_desc = "\n".join(
            f"  {i + 1}. {step.alias}: call `{step.tool_id}` with {step.params}"
            for i, step in enumerate(skill.steps)
        )
        parts += [
            "Steps:",
            steps_desc,
            "",
            "To run it end-to-end against the loaded data, call "
            f'`elliot_preview_skill(skill_id="{skill.id}")` with the inputs above.',
        ]
    body = "\n".join(parts).rstrip()
    fn = _make_body_fn(body)
    fn.__doc__ = skill.description
    mcp.prompt(name=name, description=skill.description)(fn)
    log.info("prompts.session_skill.registered", name=name, skill_id=skill.id)
    return name


def get_prompts_instructions_text() -> str:
    """Build the 'Available prompts' section of the server instructions from the
    skills actually on disk, so the advertised list can't drift from what
    ``prompts/list`` really serves."""
    skills = load_skills()
    if not skills:
        return "Available prompts (call `prompts/list` any time): (none found)"
    lines = ["Available prompts (call `prompts/list` any time):"]
    for skill in skills:
        # Keep each line short and scannable: first sentence, capped length.
        raw = (skill.description or "").strip().splitlines()[0] if skill.description else ""
        desc = raw.split(". ")[0].rstrip(".")
        if len(desc) > 90:
            desc = desc[:87].rstrip() + "…"
        lines.append(f"  - {_prompt_name(skill.name)} — {desc}")
    return "\n".join(lines)


def register_prompts(mcp: FastMCP, session: Any = None) -> int:
    """Register every plugin-root skill — and, when a session is supplied, every
    session-created skill — as an MCP prompt.

    Returns the number of prompts registered.
    """
    skills = load_skills()
    for skill in skills:
        prompt_name = _prompt_name(skill.name)
        rendered = _render_prompt_body(skill)
        fn = _make_body_fn(rendered)
        # FastMCP also uses fn.__doc__ as a description fallback. We pass the
        # description explicitly below, so this is just future-proofing.
        fn.__doc__ = skill.description
        mcp.prompt(name=prompt_name, description=skill.description)(fn)
        log.info("prompts.registered", name=prompt_name)

    count = len(skills)
    if session is not None:
        try:
            for sk in session.registry.get_all_skills():
                register_session_skill_prompt(mcp, sk)
                count += 1
        except Exception:
            log.warning("prompts.session_skills.failed", exc_info=True)
    return count
