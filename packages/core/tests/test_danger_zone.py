"""Tests for the canonical danger-zone classification."""

from __future__ import annotations

from elliot_core.danger_zone import (
    DESTRUCTIVE_VERBS,
    HIGH_IMPACT_VERBS,
    is_destructive,
    name_tokens,
)


def test_read_is_never_destructive() -> None:
    # Even a READ whose name carries a destructive verb, and even if a spec
    # mistakenly set the flag, is never the danger zone — reads don't mutate.
    assert is_destructive("READ", "delete_lookup") is False
    assert is_destructive("READ", "list_orders", explicit=True) is False


def test_explicit_flag_wins_for_writes() -> None:
    # Author's call overrides the verb heuristic in both directions.
    assert is_destructive("ACTION", "cancel_subscription", explicit=True) is True
    assert is_destructive("WRITE", "delete_order", explicit=False) is False


def test_destructive_verb_heuristic() -> None:
    assert is_destructive("WRITE", "delete_order") is True
    assert is_destructive("ACTION", "purge_cache") is True
    assert is_destructive("ACTION", "notion-delete-page") is True
    assert is_destructive("WRITE", "deleteOrder") is True  # camelCase


def test_additive_writes_are_not_destructive() -> None:
    # The whole point: additive actions run without a confirmation round-trip.
    for tool_id in ("create_order", "update_customer", "send_email", "add_item"):
        assert is_destructive("WRITE", tool_id) is False, tool_id
        assert is_destructive("ACTION", tool_id) is False, tool_id


def test_high_impact_verbs_are_not_auto_destructive() -> None:
    # High-impact but unclassified: is_destructive returns False (safe by
    # default) — it's the linter's job to nudge the author, not the runtime's to
    # silently gate. The two verb sets are disjoint.
    assert is_destructive("ACTION", "cancel_subscription") is False
    assert is_destructive("ACTION", "refund_charge") is False
    assert DESTRUCTIVE_VERBS.isdisjoint(HIGH_IMPACT_VERBS)


def test_name_tokens_splits_all_cases() -> None:
    assert name_tokens("cancel_subscription") == {"cancel", "subscription"}
    assert name_tokens("notion-delete-page") == {"notion", "delete", "page"}
    assert name_tokens("cancelSubscription") == {"cancel", "subscription"}
