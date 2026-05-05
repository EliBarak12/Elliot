import pytest

from elliot_core.errors import ElliotError
from elliot_core.tools.registry import ToolRegistry
from elliot_core.types.tool import ToolDefinition

TOOL_A = ToolDefinition(
    id="list_products",
    name="List products",
    description="Return all products",
    category="READ",
    source_ids=["products_api"],
)

TOOL_B = ToolDefinition(
    id="list_orders",
    name="List orders",
    description="Return all orders",
    category="READ",
    source_ids=["orders_api"],
)


def test_add_and_get():
    reg = ToolRegistry()
    reg.add(TOOL_A)
    assert reg.get("list_products") == TOOL_A


def test_get_all_preserves_order():
    reg = ToolRegistry()
    reg.add(TOOL_A)
    reg.add(TOOL_B)
    assert [t.id for t in reg.get_all()] == ["list_products", "list_orders"]


def test_name_conflict_raises():
    reg = ToolRegistry()
    reg.add(TOOL_A)
    duplicate = ToolDefinition(
        id="other_id",
        name="List products",  # same name
        description="Duplicate name",
        category="READ",
        source_ids=["src"],
    )
    with pytest.raises(ElliotError) as exc_info:
        reg.add(duplicate)
    assert exc_info.value.code == "TOOL_NAME_CONFLICT"


def test_update_merges():
    reg = ToolRegistry()
    reg.add(TOOL_A)
    updated = reg.update("list_products", {"limit": 50})
    assert updated.limit == 50
    assert updated.name == TOOL_A.name


def test_update_not_found_raises():
    reg = ToolRegistry()
    with pytest.raises(ElliotError) as exc_info:
        reg.update("nonexistent", {})
    assert exc_info.value.code == "TOOL_NOT_FOUND"


def test_delete():
    reg = ToolRegistry()
    reg.add(TOOL_A)
    reg.delete("list_products")
    assert reg.get("list_products") is None


def test_skills_roundtrip():
    from elliot_core.types.tool import SkillDefinition, SkillStep

    reg = ToolRegistry()
    skill = SkillDefinition(
        id="my_skill",
        name="My skill",
        description="A skill",
        steps=[SkillStep(alias="step1", tool_id="list_products", params={})],
    )
    reg.add_skill(skill)
    assert reg.get_skill("my_skill") == skill
    reg.delete_skill("my_skill")
    assert reg.get_skill("my_skill") is None
