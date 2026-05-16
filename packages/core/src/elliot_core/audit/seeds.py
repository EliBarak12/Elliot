"""Generate realistic agent-task seeds for a connector audit.

A seed is a natural-language task an agent should be able to accomplish using
only the connector's tools. Seeds drive the Petri-style parallel audit: each
seed is handed to one sub-agent. Generation is deterministic so the same
connector + intent always yields the same seeds (reproducible audits).
"""

from __future__ import annotations

import re

import structlog

from elliot_core.audit.models import AuditSeed, ProductIntent
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.tool import ToolDefinition

log = structlog.get_logger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "for",
        "in",
        "on",
        "by",
        "with",
        "all",
        "from",
        "that",
        "this",
        "is",
        "are",
        "be",
        "as",
        "it",
        "its",
        "their",
        "list",
        "get",
        "return",
        "show",
    }
)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _match_tools(text: str, tools: list[ToolDefinition], limit: int = 3) -> list[str]:
    """Rank tools by word overlap between ``text`` and each tool's id/name/description."""
    job_tokens = _tokens(text)
    if not job_tokens:
        return [t.id for t in tools[:limit]]
    scored: list[tuple[int, str]] = []
    for tool in tools:
        haystack = f"{tool.id} {tool.name} {tool.description}"
        overlap = len(job_tokens & _tokens(haystack))
        if overlap:
            scored.append((overlap, tool.id))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return [tool_id for _, tool_id in scored[:limit]]


def generate_audit_seeds(
    config: ConnectorConfig,
    intent: ProductIntent | None = None,
    limit: int = 5,
) -> list[AuditSeed]:
    """Produce up to ``limit`` audit seeds for ``config``.

    Priority order: the user's jobs-to-be-done, then a cross-tool coverage
    task, then one task per write/action tool, then one per remaining read
    tool. Always returns at least one seed.
    """
    limit = max(1, limit)
    seeds: list[AuditSeed] = []
    read_tools = [t for t in config.tools if t.category == "READ"]
    write_tools = [t for t in config.tools if t.category in ("WRITE", "ACTION")]

    def _add(task: str, suggested: list[str], job: str = "") -> None:
        if len(seeds) >= limit:
            return
        seeds.append(
            AuditSeed(
                id=f"seed-{len(seeds) + 1}",
                task=task,
                job=job,
                suggested_tools=suggested,
            )
        )

    if intent is not None:
        for job in intent.jobs_to_be_done:
            _add(
                task=(
                    f"Accomplish this real user job using only the connector's "
                    f"tools: {job}. Record every tool you call, the arguments you "
                    f"chose, and whether the result told you what to do next."
                ),
                suggested=_match_tools(job, config.tools),
                job=job,
            )

    if read_tools and len(seeds) < limit:
        sample = ", ".join(t.id for t in read_tools[:5])
        _add(
            task=(
                "Answer a realistic question about this product's data that "
                f"needs at least two read tools (candidates: {sample}). Note "
                "any field you expected but did not get back."
            ),
            suggested=[t.id for t in read_tools[:3]],
        )

    for tool in write_tools:
        _add(
            task=(
                f"Attempt the '{tool.id}' operation the way an agent would: "
                "first decide whether you have every required input, then call "
                "it. Judge whether the description made the effect, the "
                "required inputs, and the irreversibility clear."
            ),
            suggested=[tool.id],
        )

    for tool in read_tools:
        _add(
            task=(
                f"Use the connector to complete a task that depends on "
                f"'{tool.id}'. Pick argument values from the parameter "
                "descriptions — do not guess blindly — and report any "
                "parameter whose meaning was unclear."
            ),
            suggested=[tool.id],
        )

    if not seeds:
        _add(
            task=(
                "Explore every tool this connector exposes and report which "
                "ones an agent could not call confidently and why."
            ),
            suggested=[t.id for t in config.tools],
        )

    log.info("audit.seeds.generated", slug=config.slug, count=len(seeds))
    return seeds
