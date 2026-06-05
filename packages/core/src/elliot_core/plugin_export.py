"""Export a connector as an installable Codex + Claude Code plugin.

A user builds a connector with Elliot and ends up with a single
`*.connector.json` file. `export_plugin` wraps that connector in a plugin
scaffold so it can be installed natively in Codex *and* Claude Code — not
just registered as a loose MCP server.

The generated plugin serves the connector over stdio with
`elliot-mcp --connector <path>`, so it works the same way in every host that
speaks MCP. The MCP server name is the connector's `slug` — deterministic, so
the bundled skills can reference the tools as `mcp__<slug>__<tool-id>` without
anyone having to guess what the server will be called.

Every exported plugin ships skills: an auto-generated usage guide for the
connector's tools, plus one skill per workflow defined in the connector's
`skills` list. Claude Code and Codex auto-discover them from `skills/` at the
plugin root. Layout (everything resolved relative to the plugin root):

    <out>/
      .claude-plugin/plugin.json        Claude Code manifest
      .claude-plugin/marketplace.json   Claude Code marketplace catalog
      .codex-plugin/plugin.json         Codex manifest
      .agents/plugins/marketplace.json  Codex marketplace catalog
      .mcp.json                         MCP server (auto-discovered by Claude Code)
      skills/<name>/SKILL.md            agent guidance, auto-discovered
      <slug>.connector.json             the connector itself
      README.md                         install instructions
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from elliot_core.connector.serializer import deserialize_connector
from elliot_core.naming import slugify
from elliot_core.types import ConnectorConfig, SkillDefinition

log = structlog.get_logger(__name__)

# Codex sets CLAUDE_PLUGIN_ROOT alongside PLUGIN_ROOT for compatibility, and
# Claude Code expands it natively in .mcp.json — so a single placeholder works
# for both hosts.
_PLUGIN_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}"

# Every exported OSS plugin points home at Elliot Cloud — the hosted product
# that built it. Surfaced in both plugin manifests, both marketplaces, and the
# README so an installer can always trace the plugin back to its source.
_ELLIOT_CLOUD_URL = "https://elliot-cloud.com"
_ELLIOT_AUTHOR = {"name": "Elliot", "url": _ELLIOT_CLOUD_URL}


def _kebab(value: str) -> str:
    """Lowercase kebab-case slug safe for a skill directory + frontmatter name."""
    return slugify(value) or "skill"


def _mcp_server(slug: str, connector_filename: str) -> dict[str, object]:
    """The stdio MCP server entry shared by both manifests."""
    return {
        "command": "elliot-mcp",
        "args": ["--connector", f"{_PLUGIN_ROOT_VAR}/{connector_filename}"],
    }


def _claude_plugin_manifest(config: ConnectorConfig) -> dict[str, object]:
    return {
        "name": config.slug,
        "version": config.version,
        "description": config.description or f"Agent-ready tools for {config.name}.",
        "author": dict(_ELLIOT_AUTHOR),
        "homepage": _ELLIOT_CLOUD_URL,
        "keywords": ["mcp", "connector", "elliot", config.slug],
        "mcpServers": "./.mcp.json",
    }


def _claude_marketplace(config: ConnectorConfig) -> dict[str, object]:
    return {
        "name": config.slug,
        "owner": {"name": "Elliot", "url": _ELLIOT_CLOUD_URL},
        "description": f"Elliot connector plugin for {config.name}.",
        "version": config.version,
        "plugins": [
            {
                "name": config.slug,
                "source": "./",
                "description": config.description or f"Agent-ready tools for {config.name}.",
                "version": config.version,
            }
        ],
    }


def _codex_plugin_manifest(config: ConnectorConfig, connector_filename: str) -> dict[str, object]:
    short = config.description or f"Agent-ready tools for {config.name}."
    return {
        "name": config.slug,
        "version": config.version,
        "description": short,
        "author": dict(_ELLIOT_AUTHOR),
        "homepage": _ELLIOT_CLOUD_URL,
        "keywords": ["mcp", "connector", "elliot", config.slug],
        "skills": "./skills/",
        "mcpServers": {config.slug: _mcp_server(config.slug, connector_filename)},
        "interface": {
            "displayName": config.name,
            "shortDescription": short[:100],
            "longDescription": short,
            "category": "Productivity",
            "capabilities": ["Read", "Write"],
        },
    }


def _codex_marketplace(config: ConnectorConfig) -> dict[str, object]:
    return {
        "name": config.slug,
        "owner": {"name": "Elliot", "url": _ELLIOT_CLOUD_URL},
        "interface": {"displayName": config.name},
        "plugins": [
            {
                "name": config.slug,
                "source": {"source": "local", "path": "./"},
                "description": config.description or f"Agent-ready tools for {config.name}.",
                "version": config.version,
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }


def _render_usage_skill(config: ConnectorConfig) -> str:
    """Auto-generated guide: every tool the connector exposes and how to call it."""
    server = config.slug
    intro = config.description or f"Agent-ready tools for {config.name}."
    lines = [
        "---",
        f"name: {_kebab(server)}-guide",
        f"description: How to use the {config.name} connector — {intro} "
        f"Lists every tool and when to call it.",
        f"when_to_use: Trigger whenever the user wants data or actions from {config.name}.",
        f"allowed-tools: mcp__{server}__*",
        "---",
        "",
        f"# Using the {config.name} connector",
        "",
        intro,
    ]
    if config.instructions:
        lines += ["", config.instructions]
    lines += [
        "",
        f"Every tool below is served by the `{server}` MCP server, so each one is "
        f"called as `mcp__{server}__<tool-id>`.",
        "",
    ]
    if not config.tools:
        lines.append("_This connector defines no tools yet._")
        return "\n".join(lines) + "\n"

    lines.append("## Tools")
    for tool in config.tools:
        lines += [
            "",
            f"### `mcp__{server}__{tool.id}` — {tool.name} ({tool.category})",
            "",
            tool.description,
        ]
        if tool.parameters:
            lines += ["", "Parameters:"]
            for param in tool.parameters:
                req = "required" if param.required else "optional"
                desc = f" — {param.description}" if param.description else ""
                lines.append(f"- `{param.name}` ({param.type}, {req}){desc}")
    return "\n".join(lines).rstrip() + "\n"


def _render_workflow_skill(skill: SkillDefinition, config: ConnectorConfig) -> str:
    """Turn a connector workflow (SkillDefinition) into agent-facing guidance.

    A skill can be authored two ways, and either (or both) is rendered:

    - ``instructions`` — the author's own markdown becomes the skill body
      verbatim, exactly like Elliot's hand-written ``SKILL.md`` guides.
    - ``steps`` — a deterministic chain is rendered as a numbered tool list.

    When both are present, the prose leads and the steps follow as a concrete
    reference. ``when_to_use`` is taken from the author when set, otherwise a
    sensible default is generated.
    """
    server = config.slug
    when_to_use = (
        skill.when_to_use.strip()
        or f"Trigger when the user wants to {skill.name.lower()} with {config.name}."
    )
    lines = [
        "---",
        f"name: {_kebab(skill.id)}",
        f"description: {skill.description}",
        f"when_to_use: {when_to_use}",
        f"allowed-tools: mcp__{server}__*",
        "---",
        "",
        f"# {skill.name}",
        "",
        skill.description,
    ]
    if skill.input_parameters:
        lines += ["", "## Inputs", ""]
        for param in skill.input_parameters:
            req = "required" if param.required else "optional"
            desc = f" — {param.description}" if param.description else ""
            lines.append(f"- `{param.name}` ({param.type}, {req}){desc}")
    if skill.instructions.strip():
        lines += ["", skill.instructions.strip()]
    if skill.steps:
        # When the author also wrote prose, frame the chain as a concrete
        # reference rather than the whole workflow.
        heading = "## Tool sequence" if skill.instructions.strip() else "## Steps"
        lines += [
            "",
            heading,
            "",
            "Call these connector tools in order, feeding each result into the next:",
            "",
        ]
        for index, step in enumerate(skill.steps, start=1):
            params = json.dumps(step.params, sort_keys=True)
            lines.append(
                f"{index}. **{step.alias}** — call `mcp__{server}__{step.tool_id}` "
                f"with parameters `{params}`"
            )
    return "\n".join(lines).rstrip() + "\n"


def _skill_files(config: ConnectorConfig) -> dict[str, str]:
    """Map skill directory name -> SKILL.md content. Always includes the guide."""
    files: dict[str, str] = {f"{_kebab(config.slug)}-guide": _render_usage_skill(config)}
    for skill in config.skills:
        name = _kebab(skill.id)
        # Guard the rare collision with the auto guide or another workflow.
        while name in files:
            name = f"{name}-skill"
        files[name] = _render_workflow_skill(skill, config)
    return files


def _readme(config: ConnectorConfig, connector_filename: str, skill_count: int) -> str:
    tool_count = len(config.tools)
    return f"""# {config.name} — Elliot connector plugin

This plugin exposes the **{config.name}** connector ({tool_count} tool(s)) as an
MCP server you can install in Codex or Claude Code. It was generated by
`elliot export-plugin`.

> Built with **Elliot** — turn any API or database into agent-ready MCP tools
> and skills. Learn more at {_ELLIOT_CLOUD_URL}.

## MCP server name

The connector is served by an MCP server named **`{config.slug}`** (the
connector's slug). Inside an agent its tools are therefore called
`mcp__{config.slug}__<tool-id>`. The bundled skills already reference that
prefix, so nothing has to be configured by hand.

## Prerequisite

The plugin runs the connector with the `elliot-mcp` command, so that command
must be on your `PATH`:

```
uv tool install elliot-mcp-plugin
# or: pipx install elliot-mcp-plugin
```

If the connector needs secrets, export them before launching your agent — the
connector file references them as `{{{{ env:VAR }}}}` and Elliot reads them from
`ELLIOT_SECRET_*` environment variables.

## Install in Claude Code

```
/plugin marketplace add /absolute/path/to/this/folder
/plugin install {config.slug}@{config.slug}
```

## Install in Codex

```
codex plugin marketplace add /absolute/path/to/this/folder
```

Then open the plugin directory in Codex and install **{config.slug}**.

## What's inside

- `{connector_filename}` — the connector definition
- `.mcp.json` — runs `elliot-mcp --connector {connector_filename}`
- `skills/` — {skill_count} skill(s); a usage guide plus one per connector workflow
- `.claude-plugin/` — Claude Code manifest + marketplace
- `.codex-plugin/` — Codex manifest
- `.agents/plugins/marketplace.json` — Codex marketplace

---

Made with [Elliot]({_ELLIOT_CLOUD_URL}) — {_ELLIOT_CLOUD_URL}
"""


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def export_plugin(connector_path: str | Path, out_dir: str | Path) -> list[Path]:
    """Scaffold an installable Codex + Claude Code plugin from a connector file.

    Returns the list of files written. Raises FileNotFoundError if the
    connector file is missing and ElliotError if it fails to deserialize.
    """
    connector_path = Path(connector_path)
    if not connector_path.exists():
        raise FileNotFoundError(f"connector file not found: {connector_path}")

    raw = connector_path.read_text(encoding="utf-8")
    config = deserialize_connector(raw)

    out = Path(out_dir)
    connector_filename = f"{config.slug}.connector.json"

    written: list[Path] = []

    connector_dst = out / connector_filename
    connector_dst.parent.mkdir(parents=True, exist_ok=True)
    connector_dst.write_text(raw, encoding="utf-8")
    written.append(connector_dst)

    skills = _skill_files(config)
    for skill_dir, content in skills.items():
        skill_md = out / "skills" / skill_dir / "SKILL.md"
        skill_md.parent.mkdir(parents=True, exist_ok=True)
        skill_md.write_text(content, encoding="utf-8")
        written.append(skill_md)

    targets: list[tuple[Path, dict[str, object]]] = [
        (
            out / ".mcp.json",
            {"mcpServers": {config.slug: _mcp_server(config.slug, connector_filename)}},
        ),
        (out / ".claude-plugin" / "plugin.json", _claude_plugin_manifest(config)),
        (out / ".claude-plugin" / "marketplace.json", _claude_marketplace(config)),
        (
            out / ".codex-plugin" / "plugin.json",
            _codex_plugin_manifest(config, connector_filename),
        ),
        (out / ".agents" / "plugins" / "marketplace.json", _codex_marketplace(config)),
    ]
    for path, data in targets:
        _write_json(path, data)
        written.append(path)

    readme = out / "README.md"
    readme.write_text(_readme(config, connector_filename, len(skills)), encoding="utf-8")
    written.append(readme)

    log.info(
        "plugin_export.done",
        connector=config.slug,
        out_dir=str(out),
        files=len(written),
        skills=len(skills),
    )
    return written
