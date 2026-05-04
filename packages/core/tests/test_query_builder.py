from elliot_core.sqlite.engine import SQLiteEngine
from elliot_core.sqlite.flattener import flatten
from elliot_core.tools.query_builder import build_select_sql
from elliot_core.types.tool import (
    FilterCondition,
    FilterGroup,
    OrderField,
    ReturnField,
    ToolDefinition,
)


def _make_tool(**kwargs) -> ToolDefinition:
    defaults = {
        "id": "test_tool",
        "name": "Test tool",
        "description": "A test tool for query builder",
        "category": "READ",
        "source_ids": ["orders"],
    }
    return ToolDefinition(**(defaults | kwargs))


def test_select_star_no_return_fields():
    tool = _make_tool()
    sql, params = build_select_sql(tool, {})
    assert sql.startswith('SELECT * FROM "orders"')
    assert params == {}


def test_plain_return_fields():
    tool = _make_tool(return_fields=[
        ReturnField(field="name"),
        ReturnField(field="price"),
    ])
    sql, _ = build_select_sql(tool, {})
    assert '"name"' in sql
    assert '"price"' in sql
    assert "GROUP BY" not in sql


def test_aggregation_generates_group_by():
    tool = _make_tool(return_fields=[
        ReturnField(field="category"),
        ReturnField(field="price", aggregation="sum", alias="total_price"),
    ])
    sql, _ = build_select_sql(tool, {})
    assert 'SUM("price") AS "total_price"' in sql
    assert 'GROUP BY "category"' in sql


def test_count_star():
    tool = _make_tool(return_fields=[
        ReturnField(field="status"),
        ReturnField(field="*", aggregation="count", alias="num"),
    ])
    sql, _ = build_select_sql(tool, {})
    assert 'COUNT(*) AS "num"' in sql
    assert 'GROUP BY "status"' in sql


def test_having_clause():
    tool = _make_tool(
        return_fields=[
            ReturnField(field="category"),
            ReturnField(field="*", aggregation="count", alias="total"),
        ],
        having=[
            FilterGroup(conditions=[FilterCondition(field="total", operator=">", value=5)])
        ],
    )
    sql, bound = build_select_sql(tool, {})
    assert "HAVING" in sql
    assert bound  # has a fixed value bound


def test_order_by():
    tool = _make_tool(
        return_fields=[ReturnField(field="price")],
        order_by=[OrderField(field="price", direction="DESC")],
    )
    sql, _ = build_select_sql(tool, {})
    assert 'ORDER BY "price" DESC' in sql


def test_filter_with_param():
    tool = _make_tool(
        return_fields=[ReturnField(field="name")],
        filter_groups=[
            FilterGroup(conditions=[
                FilterCondition(field="category", operator="=", parameter_name="cat")
            ])
        ],
        parameters=[],
    )
    sql, bound = build_select_sql(tool, {"cat": "electronics"})
    assert "WHERE" in sql
    assert bound[next(k for k in bound)] == "electronics"


def test_optional_param_skipped():
    tool = _make_tool(
        filter_groups=[
            FilterGroup(conditions=[
                FilterCondition(field="category", operator="=", parameter_name="cat")
            ])
        ],
    )
    sql, bound = build_select_sql(tool, {})  # cat not provided
    assert "WHERE" not in sql
    assert bound == {}


def test_contains_generates_like():
    tool = _make_tool(
        filter_groups=[
            FilterGroup(conditions=[
                FilterCondition(field="name", operator="contains", parameter_name="q")
            ])
        ],
    )
    sql, bound = build_select_sql(tool, {"q": "widget"})
    assert "LIKE" in sql
    assert "%widget%" in list(bound.values())


def test_in_list_operator():
    tool = _make_tool(
        filter_groups=[
            FilterGroup(conditions=[
                FilterCondition(field="status", operator="in_list", parameter_name="statuses")
            ])
        ],
    )
    sql, bound = build_select_sql(tool, {"statuses": "active,pending"})
    assert "IN" in sql
    assert "active" in bound.values()
    assert "pending" in bound.values()


def test_end_to_end_aggregation_on_real_data():
    """Full pipeline: flatten data → load SQLite → run aggregation query."""
    data = [
        {"category": "electronics", "price": 100},
        {"category": "electronics", "price": 200},
        {"category": "clothing", "price": 50},
    ]
    engine = SQLiteEngine()
    engine.load_result(flatten(data, "products"))

    tool = _make_tool(
        source_ids=["products"],
        return_fields=[
            ReturnField(field="category"),
            ReturnField(field="price", aggregation="sum", alias="total"),
        ],
        order_by=[OrderField(field="total", direction="DESC")],
    )
    sql, bound = build_select_sql(tool, {})
    rows = engine.query(sql, bound)
    engine.close()

    assert len(rows) == 2
    assert rows[0]["category"] == "electronics"
    assert rows[0]["total"] == 300
    assert rows[1]["total"] == 50
