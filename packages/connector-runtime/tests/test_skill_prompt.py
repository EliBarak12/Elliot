"""Tests for the skill-prompt briefing an agent retrieves (``_skill_prompt_text``).

A skill can be a deterministic step chain, free-form prose, or both. The prompt
must carry whichever a skill actually has — most importantly the prose, which the
old step-only template dropped, rendering a prose-only skill as a useless empty
"Steps:" block.
"""

from __future__ import annotations

from elliot_connector_runtime.server import _skill_prompt_text
from elliot_core.types import SkillStep


def _step(alias: str, tool_id: str, params: dict | None = None) -> SkillStep:
    return SkillStep(alias=alias, tool_id=tool_id, params=params or {})


def test_prose_only_skill_includes_its_instructions_and_no_empty_steps() -> None:
    text = _skill_prompt_text(
        "Reorder",
        "Reorder a past order.",
        "the user asks to reorder something they bought before",
        [],
        "First find the customer's last order, then re-place it for the same items.",
        {},
    )
    assert "Reorder" in text
    assert "Use this when: the user asks to reorder" in text
    assert "First find the customer's last order" in text
    # A prose-only skill has no steps — it must not render an empty "Steps:" block.
    assert "Steps:" not in text


def test_deterministic_skill_lists_its_step_chain() -> None:
    steps = [
        _step("find", "search_orders", {"q": "{{ skill.input.q }}"}),
        _step("place", "create_order", {}),
    ]
    text = _skill_prompt_text("Reorder", "", "", steps, "", {})
    assert "Steps:" in text
    assert "search_orders" in text
    assert "create_order" in text


def test_hybrid_skill_shows_both_chain_and_prose() -> None:
    steps = [_step("find", "search_orders", {})]
    text = _skill_prompt_text("Reorder", "", "", steps, "Then confirm the total with the user.", {})
    assert "search_orders" in text
    assert "Then confirm the total with the user." in text


def test_description_leads_the_briefing() -> None:
    text = _skill_prompt_text("Reorder", "Reorder a past order.", "", [], "do it", {})
    assert "Execute the 'Reorder' workflow — Reorder a past order." in text


def test_supplied_inputs_are_shown() -> None:
    text = _skill_prompt_text("Reorder", "", "", [], "do it", {"order_id": "5"})
    assert "Inputs: order_id=5" in text
