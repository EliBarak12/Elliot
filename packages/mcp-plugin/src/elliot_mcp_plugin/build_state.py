"""Shared connector-assembly state helpers.

One assembly implementation, three consumers:

* ``elliot_build_connector`` — the explicit build (may select a tool subset),
* ``refresh_built_connector`` — keeps an existing build in sync after a tool
  or skill mutation, so the built snapshot can never go silently stale
  (LIVE_QA F5: update → publish shipped the OLD definition),
* ``analysis_config`` — what lint / quality-scan should look at: the FULL
  current session state, not a possibly-stale or subset snapshot (the bug that
  produced a 100/100 quality score while 22 of 23 tools went unscanned).
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog

from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.tool import ToolDefinition
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)


def connector_build_id(config: ConnectorConfig) -> str:
    """Stable short id for a built connector's content.

    A re-judge should reflect the connector that's loaded NOW, so audit
    transcripts are tagged with the build they ran against and the judge scopes
    to the current build. The id is a hash of the serialized spec, so any change
    to a tool (or its SQL/params) yields a new id and old transcripts fall out
    of scope; an identical rebuild keeps the same id.
    """
    raw = config.model_dump_json().encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def build_table_warnings(
    session: ElliotSession, tools: list[ToolDefinition]
) -> list[dict[str, Any]]:
    """Flag tools whose SQL references tables not loaded in the session.

    Only checked when the session has data materialized (post-discover) and
    only for SQL-backed tools — filter_groups / passthrough tools resolve
    their tables at runtime. Each entry names the tool and its missing tables
    so the agent can fix or drop it before publishing (audit B3).
    """
    from elliot_core.sql import referenced_base_tables

    available = set(session.engine.get_table_names())
    if not available:
        return []
    warnings: list[dict[str, Any]] = []
    for tool in tools:
        sql = session.tool_sql.get(tool.id)
        if not sql:
            continue
        # ``referenced_base_tables`` strips CTE aliases so a ``WITH x AS (...)``
        # tool is not false-flagged as referencing a missing table ``x``.
        missing = [t for t in referenced_base_tables(sql) if t not in available]
        if missing:
            warnings.append(
                {
                    "tool_id": tool.id,
                    "missing_tables": sorted(missing),
                    "message": (
                        f"Tool '{tool.id}' references table(s) "
                        f"{sorted(missing)} that are not loaded — it will fail at "
                        "call time. Fix its SQL or drop the tool before publishing."
                    ),
                }
            )
    return warnings


def assemble_connector(
    session: ElliotSession,
    *,
    name: str,
    slug: str,
    version: str,
    description: str = "",
    instructions: str = "",
    tool_ids: list[str] | None = None,
    skill_ids: list[str] | None = None,
) -> tuple[ConnectorConfig, list[ToolDefinition]]:
    """Assemble a ConnectorConfig from the session's CURRENT registry state.

    Returns the config plus the selected registry tools (pre-remap), which the
    build tool needs for table warnings.
    """
    selected_tools = (
        [t for t in session.registry.get_all() if t.id in tool_ids]
        if tool_ids is not None
        else session.registry.get_all()
    )
    selected_skills = (
        [s for s in session.registry.get_all_skills() if s.id in (skill_ids or [])]
        if skill_ids is not None
        else session.registry.get_all_skills()
    )
    referenced_source_ids = {sid for t in selected_tools for sid in t.source_ids}
    sources = [s for sid, s in session.sources.items() if sid in referenced_source_ids]

    # GAP-2: inject SQL that was stored separately back into ToolDefinition objects
    tools_with_sql = []
    for tool in selected_tools:
        sql = session.tool_sql.get(tool.id)
        if sql:
            tool = tool.model_copy(update={"sql": sql})
        tools_with_sql.append(tool)

    # GAP-3: replace UUID source IDs with human-readable source names
    uuid_to_name = {sid: src.name for sid, src in session.sources.items()}
    sources_named = [src.model_copy(update={"id": src.name}) for src in sources]
    tools_remapped = [
        tool.model_copy(
            update={"source_ids": [uuid_to_name.get(sid, sid) for sid in tool.source_ids]}
        )
        for tool in tools_with_sql
    ]

    # Session-level branding (elliot_set_branding) rides into the config;
    # fall back to what the previous build carried so a rebuild never
    # silently drops the brand.
    effective_branding = session.branding or (
        session.connector.branding if session.connector else None
    )
    config = session.builder.set_meta(
        name=name,
        slug=slug,
        version=version,
        description=description,
        instructions=instructions,
    ).build(
        sources=sources_named,
        tools=tools_remapped,
        skills=selected_skills,
        branding=effective_branding,
    )
    return config, selected_tools


def refresh_built_connector(session: ElliotSession) -> bool:
    """Re-assemble the built connector from current state, preserving its meta
    and its tool/skill selection.

    Called after a tool or skill mutation so ``session.connector`` (what export
    and cloud publish ship) always reflects the definitions as they are NOW.
    Tools/skills that were deleted simply drop out of the selection; tools
    created after the build still require an explicit ``elliot_build_connector``
    (selection is a choice, freshness is not). No-op when nothing was built.
    """
    built = session.connector
    if built is None:
        return False
    registry_ids = {t.id for t in session.registry.get_all()}
    skill_ids = {s.id for s in session.registry.get_all_skills()}
    config, _ = assemble_connector(
        session,
        name=built.name,
        slug=built.slug,
        version=built.version,
        description=built.description or "",
        instructions=built.instructions or "",
        tool_ids=[t.id for t in built.tools if t.id in registry_ids],
        skill_ids=[s.id for s in (built.skills or []) if s.id in skill_ids],
    )
    session.connector = config
    session.build_id = connector_build_id(config)
    log.info("connector.refreshed", build_id=session.build_id, tools=len(config.tools))
    return True


def analysis_config(session: ElliotSession) -> ConnectorConfig | None:
    """The config that lint / quality-scan should analyze: EVERYTHING in the
    session right now — every tool and skill, whether or not it made it into
    the last build.

    Analysis answers "is my current work agent-ready?", so scoping it to a
    stale or subset build snapshot silently hides problems (the 100/100-on-a-
    broken-draft bug). Returns ``None`` when the session has no tools at all.
    Does not mutate ``session.connector``.
    """
    if not session.registry.get_all():
        return None
    built = session.connector
    config, _ = assemble_connector(
        session,
        name=built.name if built else "draft",
        slug=built.slug if built else "draft",
        version=built.version if built else "0.0.0",
        description=(built.description or "") if built else "",
        instructions=(built.instructions or "") if built else "",
        tool_ids=None,
        skill_ids=None,
    )
    return config
