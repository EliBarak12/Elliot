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
    tool = _make_tool(
        return_fields=[
            ReturnField(field="name"),
            ReturnField(field="price"),
        ]
    )
    sql, _ = build_select_sql(tool, {})
    assert '"name"' in sql
    assert '"price"' in sql
    assert "GROUP BY" not in sql


def test_aggregation_generates_group_by():
    tool = _make_tool(
        return_fields=[
            ReturnField(field="category"),
            ReturnField(field="price", aggregation="sum", alias="total_price"),
        ]
    )
    sql, _ = build_select_sql(tool, {})
    assert 'SUM("price") AS "total_price"' in sql
    assert 'GROUP BY "category"' in sql


def test_count_star():
    tool = _make_tool(
        return_fields=[
            ReturnField(field="status"),
            ReturnField(field="*", aggregation="count", alias="num"),
        ]
    )
    sql, _ = build_select_sql(tool, {})
    assert 'COUNT(*) AS "num"' in sql
    assert 'GROUP BY "status"' in sql


def test_having_clause():
    tool = _make_tool(
        return_fields=[
            ReturnField(field="category"),
            ReturnField(field="*", aggregation="count", alias="total"),
        ],
        having=[FilterGroup(conditions=[FilterCondition(field="total", operator=">", value=5)])],
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
            FilterGroup(
                conditions=[FilterCondition(field="category", operator="=", parameter_name="cat")]
            )
        ],
        parameters=[],
    )
    sql, bound = build_select_sql(tool, {"cat": "electronics"})
    assert "WHERE" in sql
    assert bound[next(k for k in bound)] == "electronics"


def test_optional_param_skipped():
    tool = _make_tool(
        filter_groups=[
            FilterGroup(
                conditions=[FilterCondition(field="category", operator="=", parameter_name="cat")]
            )
        ],
    )
    sql, bound = build_select_sql(tool, {})  # cat not provided
    assert "WHERE" not in sql
    assert bound == {}


def test_contains_generates_like():
    tool = _make_tool(
        filter_groups=[
            FilterGroup(
                conditions=[FilterCondition(field="name", operator="contains", parameter_name="q")]
            )
        ],
    )
    sql, bound = build_select_sql(tool, {"q": "widget"})
    assert "LIKE" in sql
    assert "%widget%" in list(bound.values())


def test_contains_escapes_like_wildcards():
    """A ``contains`` value with %, _, or \\ must be escaped so it matches
    literally, and the generated clause must declare ESCAPE '\\'."""
    tool = _make_tool(
        filter_groups=[
            FilterGroup(
                conditions=[FilterCondition(field="name", operator="contains", parameter_name="q")]
            )
        ],
    )
    sql, bound = build_select_sql(tool, {"q": "100%_off\\sale"})
    # Clause declares the escape character.
    assert "ESCAPE '\\'" in sql
    bound_val = next(iter(bound.values()))
    # Wildcards in the user input are backslash-escaped; surrounding %% remain.
    assert bound_val == "%100\\%\\_off\\\\sale%"


def test_contains_wildcard_only_matches_literally():
    """An agent passing a bare '%' must not turn into a match-everything query."""
    tool = _make_tool(
        filter_groups=[
            FilterGroup(
                conditions=[FilterCondition(field="name", operator="contains", parameter_name="q")]
            )
        ],
    )
    _sql, bound = build_select_sql(tool, {"q": "%"})
    assert next(iter(bound.values())) == "%\\%%"


def test_contains_like_escaping_end_to_end():
    """Escaped wildcard is treated literally by SQLite."""
    data = [
        {"name": "50% discount"},
        {"name": "regular price"},
        {"name": "AxB"},
    ]
    engine = SQLiteEngine()
    engine.load_result(flatten(data, "items"))
    tool = _make_tool(
        source_ids=["items"],
        filter_groups=[
            FilterGroup(
                conditions=[FilterCondition(field="name", operator="contains", parameter_name="q")]
            )
        ],
    )
    # '%' must match only the literal-percent row, not every row.
    sql, bound = build_select_sql(tool, {"q": "%"})
    rows = engine.query(sql, bound)
    assert len(rows) == 1
    assert rows[0]["name"] == "50% discount"
    # '_' must match literally, not as a single-char wildcard.
    sql2, bound2 = build_select_sql(tool, {"q": "_"})
    rows2 = engine.query(sql2, bound2)
    engine.close()
    assert rows2 == []


def test_in_list_operator():
    tool = _make_tool(
        filter_groups=[
            FilterGroup(
                conditions=[
                    FilterCondition(field="status", operator="in_list", parameter_name="statuses")
                ]
            )
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


# ── dialect-aware quoting / DB push-down support ───────────────────────────


def test_build_select_sql_default_dialect_double_quotes():
    """The default (sqlite) dialect keeps ANSI double-quote identifiers."""
    tool = _make_tool(return_fields=[ReturnField(field="name")])
    sql, _ = build_select_sql(tool, {})
    assert sql.startswith('SELECT "name" FROM "orders"')


def test_build_select_sql_mysql_dialect_uses_backticks():
    tool = _make_tool(return_fields=[ReturnField(field="name")])
    sql, _ = build_select_sql(tool, {}, dialect="mysql", from_clause="`orders`")
    assert "`name`" in sql
    assert "FROM `orders`" in sql
    assert '"name"' not in sql


def test_build_select_sql_postgres_dialect_double_quotes():
    tool = _make_tool(return_fields=[ReturnField(field="name")])
    sql, _ = build_select_sql(tool, {}, dialect="postgres", from_clause='"orders"')
    assert '"name"' in sql
    assert 'FROM "orders"' in sql


def test_build_select_sql_from_clause_override():
    """from_clause replaces the FROM expression verbatim — used by the DB
    push-down to wrap a custom source query as a derived table."""
    tool = _make_tool()
    sql, _ = build_select_sql(tool, {}, from_clause="(SELECT 1) AS _elliot_src")
    assert "FROM (SELECT 1) AS _elliot_src" in sql


def test_build_select_sql_mysql_contains_escape_doubles_backslash():
    """MySQL string literals treat backslash as an escape, so the ESCAPE
    clause carries a doubled backslash there but a lone one elsewhere."""
    tool = _make_tool(
        filter_groups=[
            FilterGroup(
                conditions=[FilterCondition(field="name", operator="contains", parameter_name="q")]
            )
        ],
    )
    mysql_sql, _ = build_select_sql(tool, {"q": "ab"}, dialect="mysql", from_clause="`t`")
    assert "ESCAPE '\\\\'" in mysql_sql

    sqlite_sql, _ = build_select_sql(tool, {"q": "ab"})
    assert "ESCAPE '\\'" in sqlite_sql
    assert "ESCAPE '\\\\'" not in sqlite_sql


def test_quote_ident_dialects():
    from elliot_core.tools.query_builder import quote_ident

    assert quote_ident("orders") == '"orders"'
    assert quote_ident("orders", "postgres") == '"orders"'
    assert quote_ident("orders", "mysql") == "`orders`"


def test_quote_ident_rejects_bad_identifier():
    import pytest

    from elliot_core.errors import ElliotError
    from elliot_core.tools.query_builder import quote_ident

    with pytest.raises(ElliotError):
        quote_ident("orders; DROP TABLE x", "mysql")
