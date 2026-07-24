"""Canonical danger-zone classification for connector tools.

A single source of truth for "is this tool the danger zone?" — an irreversible
mutation a client should gate behind confirmation rather than auto-run.

Elliot's whole value for WRITE/ACTION tools is that an agent operates them for
the user *without* a confirmation round-trip; only the genuinely destructive
subset is gated. That one distinction drives four separate surfaces — the
runtime's confirmation gate, the MCP ``destructiveHint`` annotation, the
linter, and the agent briefing — so it must be computed the same way
everywhere. This module is that shared definition; each surface imports from
here instead of keeping its own copy, so a connector can never be gated one way
and labelled another (the drift this module was extracted to end: the runtime
gated correctly while ``schema_gen`` annotated every write as destructive).
"""

from __future__ import annotations

import re

# Verbs that mark a WRITE/ACTION tool as the "danger zone" — an irreversible
# mutation a client should gate behind human approval rather than auto-run.
# Ordinary additive actions (create/update/send) are deliberately NOT
# destructive: an agentic connector's whole value is operating them for the
# user without a confirmation round-trip — only the danger zone is gated.
DESTRUCTIVE_VERBS = frozenset(
    {"delete", "remove", "destroy", "drop", "purge", "wipe", "erase", "truncate", "reset", "revoke"}
)

# High-impact verbs the destructive heuristic above does NOT auto-detect. An
# unclassified WRITE/ACTION tool carrying one of these is almost always
# irreversible (money moves, access pulled, a commitment ends), yet
# ``is_destructive`` treats it as safe until the author sets ``destructive``.
# The linter uses this set to WARN (DESTRUCTIVE_NOT_FLAGGED) so the author makes
# an explicit call; it is deliberately disjoint from ``DESTRUCTIVE_VERBS`` and
# kept tight to avoid nagging on benign toggles (disable/close/expire).
HIGH_IMPACT_VERBS = frozenset(
    {
        "cancel",
        "refund",
        "chargeback",
        "payout",
        "deactivate",
        "suspend",
        "terminate",
        "void",
        "ban",
        "deprovision",
        "withdraw",
        "unpublish",
        "unsubscribe",
    }
)


def name_tokens(name: str) -> set[str]:
    """Lowercased word tokens of a tool name, splitting snake_case, kebab-case
    and camelCase alike (``delete_order`` / ``notion-delete-page`` /
    ``deleteOrder`` all yield a ``delete`` token)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return {t.lower() for t in re.split(r"[^a-zA-Z0-9]+", spaced) if t}


def is_destructive(category: str, tool_id: str, explicit: bool | None = None) -> bool:
    """Whether a tool is the danger zone: an irreversible mutation clients must
    gate. An explicit ``destructive`` flag on the tool wins when set — so an
    author can mark a business-critical action the verbs miss (``execute_refund``,
    ``cancel_subscription``, ``send_payout``) as the danger zone, or clear a false
    positive. Otherwise: READ tools are never destructive; among WRITE/ACTION
    tools, only those whose name carries a destructive verb (delete/remove/drop/
    purge…) qualify — additive creates and updates run without a prompt."""
    # READs never mutate, so they are never the danger zone — even if a
    # hand-authored spec set the flag (a "destructive read" would emit a
    # contradictory readOnlyHint + destructiveHint pair). The explicit flag then
    # wins for WRITE/ACTION tools, and the verb heuristic is the fallback.
    if category == "READ":
        return False
    if explicit is not None:
        return explicit
    return not name_tokens(tool_id).isdisjoint(DESTRUCTIVE_VERBS)
