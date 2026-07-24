"""Tests for ToolExecutor."""

from __future__ import annotations

import httpx
import pytest
import respx

from elliot_connector_runtime.executor import (
    ExecutorError,
    ToolExecutor,
    _extract_table_names,
    _interpolate,
)
from elliot_core.types import (
    ConnectorConfig,
    PaginationConfig,
    ParameterDefinition,
    ReturnField,
    SourceConfig,
    ToolDefinition,
)

CONNECTOR = ConnectorConfig(
    name="Pets",
    slug="pets",
    version="1.0.0",
    sources=[
        SourceConfig(
            id="animals",
            name="Animals API",
            type="rest",
            url="https://api.example.com/animals",
            data_path="items",
        )
    ],
    tools=[
        ToolDefinition(
            id="list_animals",
            name="List animals",
            description="List all animals",
            category="READ",
            sql="SELECT * FROM animals WHERE species = :species",
            parameters=[
                ParameterDefinition(name="species", type="string", required=True, description="")
            ],
        )
    ],
    skills=[],
)


def test_extract_table_names() -> None:
    sql = "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.id"
    assert _extract_table_names(sql) == ["orders", "customers"]


def test_extract_table_names_deduplicates() -> None:
    sql = "SELECT * FROM items JOIN items AS i2 ON items.id = i2.parent_id"
    assert _extract_table_names(sql) == ["items"]


def test_extract_table_names_quoted() -> None:
    """build_select_sql generates double-quoted table names; these must be extracted."""
    sql = 'SELECT "id", "name" FROM "customers" ORDER BY "name" DESC LIMIT 50'
    assert _extract_table_names(sql) == ["customers"]


def test_extract_table_names_quoted_join() -> None:
    sql = 'SELECT * FROM "orders" JOIN "customers" ON "orders"."cid" = "customers"."id"'
    assert _extract_table_names(sql) == ["orders", "customers"]


def test_interpolate() -> None:
    url = "https://api.example.com/users/{user_id}/posts"
    result = _interpolate(url, {"user_id": "42"})
    assert result == "https://api.example.com/users/42/posts"


def test_interpolate_no_placeholders() -> None:
    url = "https://api.example.com/users"
    assert _interpolate(url, {"user_id": "42"}) == url


def test_interpolate_percent_encodes_values() -> None:
    """Agent-supplied values are encoded so they cannot escape the path."""
    url = "https://api.example.com/users/{user_id}/posts"
    result = _interpolate(url, {"user_id": "../admin?force=1"})
    assert "../admin" not in result
    assert result == "https://api.example.com/users/..%2Fadmin%3Fforce%3D1/posts"


def _file_connector(content: str, fmt: str = "json", *, encoding: str = "text") -> ConnectorConfig:
    return ConnectorConfig(
        name="Files",
        slug="files",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="people",
                name="People",
                type="file",
                content=content,
                content_encoding=encoding,  # type: ignore[arg-type]
                format=fmt,  # type: ignore[arg-type]
                table_name="people",
            )
        ],
        tools=[
            ToolDefinition(
                id="list_people",
                name="List people",
                description="List people from the uploaded file.",
                category="READ",
                source_ids=["people"],
                sql="SELECT * FROM people WHERE name = :name",
                parameters=[
                    ParameterDefinition(name="name", type="string", required=True, description="")
                ],
            )
        ],
        skills=[],
    )


async def test_executor_file_source_inline_content_no_disk() -> None:
    """E2E gap-2 fix: a PUBLISHED connector whose file source carries its bytes
    inline materializes and serves queries with NO file on disk anywhere — the
    runtime instance has no access to the builder's workspace."""
    connector = _file_connector('[{"id": 1, "name": "Ada"}, {"id": 2, "name": "Lin"}]')
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"name": "Ada"})
    assert len(result.rows) == 1
    assert result.rows[0]["id"] == 1


async def test_executor_file_source_inline_base64() -> None:
    import base64 as _b64

    raw = _b64.b64encode(b"id,name\n1,Ada\n2,Lin\n").decode("ascii")
    connector = _file_connector(raw, fmt="csv", encoding="base64")
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"name": "Lin"})
    assert len(result.rows) == 1
    assert result.rows[0]["id"] == "2"


async def test_executor_file_source_path_outside_allowlist_refused(tmp_path, monkeypatch) -> None:
    """ATTACK: a published spec whose file source points at an arbitrary host
    path (no inline content) must NOT be able to read it — containment holds
    inside the runtime executor too."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ELLIOT_FILE_ROOT", str(tmp_path))
    monkeypatch.delenv("ELLIOT_FILE_READER_ALLOW_ABSOLUTE", raising=False)
    secret = tmp_path.parent / "victim.json"
    secret.write_text('[{"name": "Ada", "pw": "hunter2"}]')
    connector = ConnectorConfig(
        name="Files",
        slug="files",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="people", name="People", type="file", path=str(secret), table_name="people"
            )
        ],
        tools=[
            ToolDefinition(
                id="list_people",
                name="List people",
                description="List people.",
                category="READ",
                source_ids=["people"],
                sql="SELECT * FROM people",
            )
        ],
        skills=[],
    )
    from elliot_core.errors import ElliotError

    executor = ToolExecutor(connector, secrets={})
    with pytest.raises(ElliotError) as ei:
        await executor.execute(connector.tools[0], {})
    assert ei.value.code == "FILE_NOT_ALLOWED"


@respx.mock
async def test_executor_rest_source() -> None:
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": 1, "species": "cat", "name": "Whiskers"}]},
        )
    )

    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "cat"})

    assert len(result.rows) == 1
    assert result.rows[0]["name"] == "Whiskers"
    assert result.tool_id == "list_animals"


@respx.mock
async def test_executor_rest_passthrough_forwards_query_params() -> None:
    """A READ tool with rest_query_params forwards them to the REST source as
    live query-string params on every call (e.g. ?resource_id=<arg>)."""
    connector = ConnectorConfig(
        name="DataStore",
        slug="datastore",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="search",
                name="Search",
                type="rest",
                url="https://api.example.com/search",
            )
        ],
        tools=[
            ToolDefinition(
                id="search_records",
                name="Search records",
                description="Search a resource's records live.",
                category="READ",
                source_ids=["search"],
                rest_query_params=["resource_id", "q"],
                parameters=[
                    ParameterDefinition(
                        name="resource_id", type="string", required=True, description="resource id"
                    ),
                    ParameterDefinition(
                        name="q", type="string", required=False, description="text filter"
                    ),
                ],
            )
        ],
        skills=[],
    )
    route = respx.get("https://api.example.com/search").mock(
        return_value=httpx.Response(200, json={"records": [{"id": 1, "name": "Ada"}]})
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"resource_id": "abc-123", "q": "ada"})

    assert len(result.rows) == 1
    assert result.rows[0]["name"] == "Ada"
    # The agent's params were forwarded as live query-string params.
    sent = str(route.calls.last.request.url)
    assert "resource_id=abc-123" in sent
    assert "q=ada" in sent


@respx.mock
async def test_executor_passthrough_post_sends_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A passthrough source with method=POST and forward_params_in='body' issues
    a real POST with the params in the JSON body. Previously the runtime sent
    every passthrough fetch as GET, dropping the body entirely."""
    import json

    monkeypatch.setenv("ECOMTOKEN", "ecom-xyz")
    connector = ConnectorConfig(
        name="Catalog",
        slug="catalog",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="catalog",
                name="Catalog",
                type="rest",
                url="https://api.example.com/catalog",
                method="POST",
                forward_params_in="body",
                body={"aggs": 1},
                headers={"ecomtoken": "{{ env:ECOMTOKEN }}"},
                data_path="data",
            )
        ],
        tools=[
            ToolDefinition(
                id="search_catalog",
                name="Search catalog",
                description="Search the catalog live by a body-driven query.",
                category="READ",
                source_ids=["catalog"],
                rest_query_params=["q", "store"],
                parameters=[
                    ParameterDefinition(name="q", type="string", description="term"),
                    ParameterDefinition(name="store", type="string", description="store id"),
                ],
            )
        ],
        skills=[],
    )
    route = respx.post("https://api.example.com/catalog").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "name": "Cottage"}]})
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"q": "cottage", "store": "331"})

    assert result.rows[0]["name"] == "Cottage"
    req = route.calls.last.request
    assert req.method == "POST"
    assert json.loads(req.content) == {"aggs": 1, "q": "cottage", "store": "331"}
    assert req.url.query == b""
    assert req.headers["ecomtoken"] == "ecom-xyz"


@respx.mock
async def test_executor_empty_result() -> None:
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "dragon"})
    assert result.rows == []


@respx.mock
async def test_executor_rest_source_row_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """A REST source with huge pages is truncated at ELLIOT_MAX_RESULT_ROWS so
    pagination cannot OOM the worker even before max_pages bites."""
    monkeypatch.setenv("ELLIOT_MAX_RESULT_ROWS", "3")
    # Page returns more rows than the cap; data_path "items" unwraps them.
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": i, "species": "cat"} for i in range(20)]},
        )
    )
    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "cat"})
    # Materialized rows are capped at 3, so the WHERE species='cat' query
    # cannot return more than 3.
    assert len(result.rows) <= 3
    # The snapshot was capped at fetch time, so the result must NOT pretend to
    # be complete — it is flagged as a source-level truncation so the agent is
    # told the underlying data may be missing rows (principle 3).
    assert result.truncated is True
    assert result.truncation_reason == "source_cap"


def test_scrub_removes_resolved_secrets_from_error_text() -> None:
    """An upstream error string (e.g. an httpx URL with ?api_key=...) must have
    resolved secret values scrubbed before it is logged — secrets never logged."""
    secret = "sk_live_VERYsecret123"
    executor = ToolExecutor(CONNECTOR, secrets={"API_KEY": secret, "X": "ab"})
    msg = f"Client error '401' for url 'https://api.example.com/x?api_key={secret}'"
    scrubbed = executor._scrub(msg)
    assert secret not in scrubbed
    assert "***" in scrubbed
    # Trivially short values are not masked (avoids redacting noise).
    assert executor._scrub("value ab here") == "value ab here"


def test_fit_rows_to_token_budget() -> None:
    from elliot_connector_runtime.executor import _fit_rows_to_token_budget

    rows = [{"blob": "x" * 4000} for _ in range(10)]  # each ~1k tokens
    # A 2500-token budget fits ~2 rows; never returns zero.
    kept = _fit_rows_to_token_budget(rows, 2500)
    assert 1 <= kept < 10
    # A single oversized row is still returned (can't go below one).
    assert _fit_rows_to_token_budget([{"blob": "x" * 80_000}], 100) == 1
    # A generous budget keeps everything.
    assert _fit_rows_to_token_budget(rows, 1_000_000) == 10


def test_payload_includes_token_estimate_and_token_budget_note() -> None:
    from elliot_connector_runtime.server import _payload_for
    from elliot_core.types import QueryResult

    # Every result carries an estimated_tokens count for the agent.
    plain = _payload_for(QueryResult(rows=[{"a": 1}], tool_id="t"))
    assert plain["count"] == 1
    assert isinstance(plain["estimated_tokens"], int) and plain["estimated_tokens"] > 0
    assert "truncated" not in plain

    # A token-budget truncation surfaces an actionable note pointing at fields.
    capped = _payload_for(
        QueryResult(
            rows=[{"a": 1}],
            tool_id="t",
            truncated=True,
            total_rows=50,
            truncation_reason="token_budget",
        )
    )
    assert capped["truncated"] is True
    assert "field" in capped["truncation_note"].lower()
    assert "1 of 50" in capped["truncation_note"]


def test_empty_read_result_notes_the_supplied_filters() -> None:
    from elliot_connector_runtime.server import _payload_for
    from elliot_core.types import QueryResult, ToolDefinition

    tool = ToolDefinition.model_validate(
        {
            "id": "search_people",
            "name": "Search people",
            "description": "Search people by name.",
            "category": "READ",
            "source_ids": ["people"],
            "parameters": [{"name": "q", "type": "string", "required": False}],
        }
    )
    out = _payload_for(QueryResult(rows=[], tool_id="search_people"), tool, {"q": "zzz"})
    assert out["count"] == 0
    assert out["empty"] is True
    assert "q" in out["empty_note"]
    assert "genuinely empty" in out["empty_note"]


def test_empty_read_with_no_args_says_the_source_is_empty() -> None:
    from elliot_connector_runtime.server import _payload_for
    from elliot_core.types import QueryResult, ToolDefinition

    tool = ToolDefinition.model_validate(
        {
            "id": "list_people",
            "name": "List people",
            "description": "List all people.",
            "category": "READ",
            "source_ids": ["people"],
            "parameters": [{"name": "q", "type": "string", "required": False}],
        }
    )
    out = _payload_for(QueryResult(rows=[], tool_id="list_people"), tool, {})
    assert out["empty"] is True
    assert "no arguments" in out["empty_note"]


def test_empty_write_result_has_no_empty_note() -> None:
    # An empty mutation result is normal — no "widen your filter" note.
    from elliot_connector_runtime.server import _payload_for
    from elliot_core.types import QueryResult, ToolDefinition

    tool = ToolDefinition.model_validate(
        {
            "id": "create_person",
            "name": "Create person",
            "description": "Create a person.",
            "category": "WRITE",
            "source_ids": ["people"],
            "api_mapping": {"method": "POST", "body_params": ["name"]},
            "parameters": [{"name": "name", "type": "string", "required": True}],
        }
    )
    out = _payload_for(QueryResult(rows=[], tool_id="create_person"), tool, {"name": "Ada"})
    assert "empty" not in out
    assert "empty_note" not in out


def test_non_empty_read_result_has_no_empty_note() -> None:
    from elliot_connector_runtime.server import _payload_for
    from elliot_core.types import QueryResult, ToolDefinition

    tool = ToolDefinition.model_validate(
        {
            "id": "list_people",
            "name": "List people",
            "description": "List people.",
            "category": "READ",
            "source_ids": ["people"],
            "parameters": [],
        }
    )
    out = _payload_for(QueryResult(rows=[{"id": 1}], tool_id="list_people"), tool, {})
    assert "empty" not in out


@respx.mock
async def test_executor_token_budget_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rows that fit the row cap but are individually large are trimmed to the
    per-call token budget — 'sized for context windows', not just 'N rows'."""
    monkeypatch.setenv("ELLIOT_MAX_RESULT_ROWS", "1000")
    monkeypatch.setenv("ELLIOT_MAX_RESULT_TOKENS", "1500")
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": i, "species": "cat", "bio": "x" * 4000} for i in range(20)]},
        )
    )
    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "cat"})
    assert result.truncated is True
    assert result.truncation_reason == "token_budget"
    assert result.total_rows == 20
    assert 0 < len(result.rows) < 20


@respx.mock
async def test_executor_rest_source_under_cap_not_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A REST source whose snapshot fits under the cap is not flagged: the
    source-truncation marker must not fire on complete data."""
    from elliot_connector_runtime.server import _result_truncated

    monkeypatch.setenv("ELLIOT_MAX_RESULT_ROWS", "50")
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": i, "species": "cat"} for i in range(5)]},
        )
    )
    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "cat"})
    assert result.truncated is False
    assert result.truncation_reason is None
    assert _result_truncated(result) is False


@respx.mock
async def test_executor_cursor_pagination_with_data_path() -> None:
    """Cursor is read from the raw envelope even when data_path narrows the
    response to a bare list that no longer carries next_cursor."""
    from elliot_core.types import PaginationConfig

    connector = ConnectorConfig(
        name="Pets",
        slug="pets",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="animals",
                name="Animals API",
                type="rest",
                url="https://api.example.com/animals",
                data_path="items",
                pagination=PaginationConfig(strategy="cursor", max_pages=5),
            )
        ],
        tools=[CONNECTOR.tools[0]],
        skills=[],
    )
    route = respx.get("https://api.example.com/animals")
    route.side_effect = [
        httpx.Response(200, json={"items": [{"id": 1, "species": "cat"}], "next_cursor": "p2"}),
        httpx.Response(200, json={"items": [{"id": 2, "species": "cat"}]}),
    ]
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"species": "cat"})
    # Without the envelope fix, page 2 is never fetched and only id=1 is seen.
    assert {r["id"] for r in result.rows} == {1, 2}


async def test_executor_no_sql_no_filter_groups_raises() -> None:
    """A tool with no sql AND empty filter_groups AND empty return_fields raises ExecutorError.

    The elif uses truthiness so that default empty lists fall through to the else clause.
    """
    connector = ConnectorConfig(
        name="Empty",
        slug="empty",
        version="1.0.0",
        sources=[SourceConfig(id="somewhere", name="Somewhere", type="rest", url="http://x.com")],
        tools=[
            ToolDefinition(
                id="no_sql_tool",
                name="No SQL",
                description="Tool without SQL",
                category="READ",
                sql=None,
                source_ids=["somewhere"],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    tool = connector.tools[0]
    with pytest.raises(ExecutorError, match="no sql or filter_groups defined"):
        await executor.execute(tool, {})


async def test_executor_file_source(tmp_path: pytest.TempPathFactory) -> None:
    """File sources are loaded directly without HTTP."""
    import json

    data_file = tmp_path / "items.json"
    data_file.write_text(json.dumps([{"id": 1, "name": "widget"}, {"id": 2, "name": "gadget"}]))

    connector = ConnectorConfig(
        name="FileTest",
        slug="file-test",
        version="1.0.0",
        sources=[
            SourceConfig(id="items", name="Items", type="file", path=str(data_file), format="json")
        ],
        tools=[
            ToolDefinition(
                id="list_items",
                name="List items",
                description="List all items",
                category="READ",
                sql="SELECT * FROM items",
                parameters=[],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})

    assert len(result.rows) == 2
    assert result.rows[0]["name"] == "widget"


async def test_executor_file_source_with_filter(tmp_path: pytest.TempPathFactory) -> None:
    """File source with parameterized SQL filters correctly."""
    import json

    data_file = tmp_path / "products.json"
    data_file.write_text(
        json.dumps(
            [
                {"id": 1, "category": "electronics", "price": 99},
                {"id": 2, "category": "clothing", "price": 49},
                {"id": 3, "category": "electronics", "price": 199},
            ]
        )
    )

    connector = ConnectorConfig(
        name="Products",
        slug="products",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="products", name="Products", type="file", path=str(data_file), format="json"
            )
        ],
        tools=[
            ToolDefinition(
                id="list_by_category",
                name="List by category",
                description="Filter products by category",
                category="READ",
                sql="SELECT * FROM products WHERE category = :category",
                parameters=[
                    ParameterDefinition(
                        name="category", type="string", required=True, description=""
                    )
                ],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"category": "electronics"})

    assert len(result.rows) == 2
    assert all(r["category"] == "electronics" for r in result.rows)


async def test_executor_unsupported_source_raises() -> None:
    """Unknown source types raise ExecutorError."""
    connector = ConnectorConfig(
        name="Bad",
        slug="bad",
        version="1.0.0",
        sources=[SourceConfig(id="x", name="X", type="rest", url="http://x.com")],
        tools=[
            ToolDefinition(
                id="t",
                name="T",
                description="T",
                category="READ",
                sql="SELECT * FROM x",
                parameters=[],
            )
        ],
        skills=[],
    )
    # Patch the source type to something unsupported after construction
    executor = ToolExecutor(connector, secrets={})
    executor._sources["x"].type = "graphql"  # type: ignore[assignment]
    with pytest.raises(ExecutorError, match="Unsupported source type"):
        await executor.execute(connector.tools[0], {})


@respx.mock
async def test_executor_unknown_source_skipped() -> None:
    """Table names in SQL that don't match any source are silently skipped."""
    respx.get("https://api.example.com/animals").mock(
        return_value=httpx.Response(
            200,
            json={"items": [{"id": 1, "species": "dog", "name": "Rex"}]},
        )
    )

    tool = CONNECTOR.tools[0]
    executor = ToolExecutor(CONNECTOR, secrets={})
    result = await executor.execute(tool, {"species": "dog"})
    assert result.rows[0]["name"] == "Rex"


async def test_executor_flattens_nested_json_source(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Regression: connector tools authored against flattener-shaped names
    (e.g. `insights` plus child `insights_facts`) used to fail with
    `no such table` because the runtime only ingested a single flat table
    named after `source.id`. The executor must run the flattener so both
    primary and child tables exist with their authored names.
    """
    import json

    data_file = tmp_path / "insights.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": "a",
                    "label": "north",
                    "facts": [
                        {"k": "visits", "v": 10},
                        {"k": "signups", "v": 2},
                    ],
                },
                {
                    "id": "b",
                    "label": "south",
                    "facts": [{"k": "visits", "v": 5}],
                },
            ]
        )
    )

    connector = ConnectorConfig(
        name="Insights",
        slug="insights",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="src-uuid-1234",
                name="insights",
                type="file",
                path=str(data_file),
                format="json",
                # Studio sets table_name during discovery — that's what
                # tool SQL is authored against.
                table_name="insights",
            )
        ],
        tools=[
            ToolDefinition(
                id="overview",
                name="Overview",
                description="Top-level rows",
                category="READ",
                sql='SELECT * FROM "insights"',
                source_ids=["src-uuid-1234"],
            ),
            ToolDefinition(
                id="facts",
                name="Facts",
                description="Nested facts via child table",
                category="READ",
                sql='SELECT * FROM "insights_facts"',
                source_ids=["src-uuid-1234"],
            ),
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})

    overview = await executor.execute(connector.tools[0], {})
    assert {r["label"] for r in overview.rows} == {"north", "south"}

    facts = await executor.execute(connector.tools[1], {})
    assert len(facts.rows) == 3
    assert {r["k"] for r in facts.rows} == {"visits", "signups"}


async def test_executor_missing_table_raises_actionable_error(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """SQL referencing a table the connector didn't materialize gets a
    typed error naming the missing tables — not a raw `no such table`."""
    import json

    from elliot_core.errors import ElliotError

    data_file = tmp_path / "items.json"
    data_file.write_text(json.dumps([{"id": 1}]))

    connector = ConnectorConfig(
        name="Bad",
        slug="bad",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="items",
                name="items",
                type="file",
                path=str(data_file),
                format="json",
                table_name="items",
            )
        ],
        tools=[
            ToolDefinition(
                id="broken",
                name="Broken",
                description="references a table that was never materialized",
                category="READ",
                sql='SELECT * FROM "nonexistent_table"',
                source_ids=["items"],
            )
        ],
        skills=[],
    )

    executor = ToolExecutor(connector, secrets={})
    with pytest.raises(ElliotError) as exc:
        await executor.execute(connector.tools[0], {})
    assert exc.value.code == "TABLE_NOT_FOUND"
    assert "nonexistent_table" in exc.value.message
    assert exc.value.detail is not None
    assert "nonexistent_table" in exc.value.detail["missing_tables"]


async def test_executor_materialization_is_cached(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Second call against the same source must not re-read the file
    (a 4.7 MB file shouldn't be flattened on every tool call)."""
    import json

    data_file = tmp_path / "items.json"
    data_file.write_text(json.dumps([{"id": 1, "name": "first"}]))

    connector = ConnectorConfig(
        name="Items",
        slug="items",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="items",
                name="items",
                type="file",
                path=str(data_file),
                format="json",
                table_name="items",
            )
        ],
        tools=[
            ToolDefinition(
                id="list",
                name="List",
                description="List items",
                category="READ",
                sql='SELECT * FROM "items"',
                source_ids=["items"],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})

    first = await executor.execute(connector.tools[0], {})
    assert first.rows[0]["name"] == "first"

    # Mutate the file. If the executor refetches every call, we'd see "second".
    data_file.write_text(json.dumps([{"id": 1, "name": "second"}]))

    second = await executor.execute(connector.tools[0], {})
    assert second.rows[0]["name"] == "first"


async def test_executor_materialization_ttl_refresh(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """When TTL is 0 every call re-materializes — used to verify the TTL
    branch in the cache, and to give operators a way to opt out."""
    import json

    data_file = tmp_path / "items.json"
    data_file.write_text(json.dumps([{"id": 1, "name": "v1"}]))

    connector = ConnectorConfig(
        name="Items",
        slug="items",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="items",
                name="items",
                type="file",
                path=str(data_file),
                format="json",
                table_name="items",
            )
        ],
        tools=[
            ToolDefinition(
                id="list",
                name="List",
                description="List items",
                category="READ",
                sql='SELECT * FROM "items"',
                source_ids=["items"],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={}, materialization_ttl_seconds=0)

    first = await executor.execute(connector.tools[0], {})
    assert first.rows[0]["name"] == "v1"

    data_file.write_text(json.dumps([{"id": 1, "name": "v2"}]))

    second = await executor.execute(connector.tools[0], {})
    assert second.rows[0]["name"] == "v2"


async def test_executor_falls_back_to_all_sources_when_source_ids_empty(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Tools that don't declare source_ids still materialize every source —
    keeps older connector definitions working."""
    import json

    items_file = tmp_path / "items.json"
    items_file.write_text(json.dumps([{"id": 1, "name": "widget"}]))

    connector = ConnectorConfig(
        name="Items",
        slug="items",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="items",
                name="items",
                type="file",
                path=str(items_file),
                format="json",
                table_name="items",
            )
        ],
        tools=[
            ToolDefinition(
                id="list",
                name="List items",
                description="No source_ids — fall back to all sources",
                category="READ",
                sql='SELECT * FROM "items"',
                # NOTE: no source_ids
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})
    assert result.rows[0]["name"] == "widget"


# ── DB filter push-down ────────────────────────────────────────────────────


def test_db_from_clause_table() -> None:
    """A DB source with a table name yields a dialect-quoted FROM."""
    from elliot_connector_runtime.executor import _db_from_clause

    src = SourceConfig(id="db", name="DB", type="postgres", table="orders")
    assert _db_from_clause(src, "postgres") == '"orders"'
    assert _db_from_clause(src, "mysql") == "`orders`"


def test_db_from_clause_wraps_custom_query() -> None:
    """A DB source with a custom query is wrapped as a derived table so the
    tool's WHERE / LIMIT can layer on top of it."""
    from elliot_connector_runtime.executor import _db_from_clause

    src = SourceConfig(
        id="db", name="DB", type="postgres", query="SELECT * FROM orders WHERE active"
    )
    assert _db_from_clause(src, "postgres") == "(SELECT * FROM orders WHERE active) AS _elliot_src"


def test_db_from_clause_rejects_non_select_query() -> None:
    from elliot_connector_runtime.executor import _db_from_clause

    src = SourceConfig(id="db", name="DB", type="postgres", query="DROP TABLE orders")
    with pytest.raises(ExecutorError, match="invalid query"):
        _db_from_clause(src, "postgres")


def test_db_from_clause_requires_table_or_query() -> None:
    from elliot_connector_runtime.executor import _db_from_clause

    src = SourceConfig(id="db", name="DB", type="postgres", url="postgresql://x/y")
    with pytest.raises(ExecutorError, match="neither 'table' nor 'query'"):
        _db_from_clause(src, "postgres")


async def test_executor_db_pushdown_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    """A filter_groups tool on a single Postgres source pushes its WHERE
    straight to the database instead of snapshotting the whole table."""
    from elliot_core.sources import db_connector
    from elliot_core.types.source import FetchResult
    from elliot_core.types.tool import FilterCondition, FilterGroup

    captured: dict[str, str] = {}

    def fake_run_select(
        config: SourceConfig,
        secrets: dict[str, str],
        sql: str,
        params: dict[str, object] | None,
    ) -> FetchResult:
        captured["sql"] = sql
        captured["params"] = str(params)
        captured["source_id"] = config.id
        return FetchResult(rows=[{"id": 1, "status": "open"}], fetched_at="2026-01-01T00:00:00Z")

    monkeypatch.setattr(db_connector, "run_select", fake_run_select)

    connector = ConnectorConfig(
        name="Orders",
        slug="orders",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="db",
                name="DB",
                type="postgres",
                url="postgresql://localhost/test",
                table="orders",
            )
        ],
        tools=[
            ToolDefinition(
                id="orders_by_status",
                name="Orders by status",
                description="List orders filtered by status",
                category="READ",
                source_ids=["db"],
                filter_groups=[
                    FilterGroup(
                        conditions=[
                            FilterCondition(field="status", operator="=", parameter_name="status")
                        ]
                    )
                ],
                parameters=[
                    ParameterDefinition(name="status", type="string", required=True, description="")
                ],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {"status": "open"})

    assert result.rows == [{"id": 1, "status": "open"}]
    assert captured["source_id"] == "db"
    assert 'FROM "orders"' in captured["sql"]
    assert "WHERE" in captured["sql"]
    # The agent's parameter value reaches the bound params of the real query.
    assert "open" in captured["params"]


async def test_executor_db_pushdown_mysql(monkeypatch: pytest.MonkeyPatch) -> None:
    """MySQL push-down quotes identifiers with backticks."""
    from elliot_core.sources import db_connector
    from elliot_core.types.source import FetchResult

    captured: dict[str, str] = {}

    def fake_run_select(
        config: SourceConfig,
        secrets: dict[str, str],
        sql: str,
        params: dict[str, object] | None,
    ) -> FetchResult:
        captured["sql"] = sql
        return FetchResult(rows=[{"order_id": 9}], fetched_at="x")

    monkeypatch.setattr(db_connector, "run_select", fake_run_select)

    connector = ConnectorConfig(
        name="Shop",
        slug="shop",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="db",
                name="DB",
                type="mysql",
                url="mysql+pymysql://root:pass@localhost/test",
                table="orders",
            )
        ],
        tools=[
            ToolDefinition(
                id="recent_orders",
                name="Recent orders",
                description="List recent order ids",
                category="READ",
                source_ids=["db"],
                return_fields=[ReturnField(field="order_id")],
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})

    assert result.rows == [{"order_id": 9}]
    assert "FROM `orders`" in captured["sql"]
    assert "`order_id`" in captured["sql"]


async def test_executor_db_pushdown_skipped_for_raw_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    """A DB tool with raw SQL keeps the SQLite-snapshot path — its SQL is
    authored in the SQLite dialect, so it cannot be pushed to Postgres."""
    from elliot_core.sources import db_connector
    from elliot_core.types.source import FetchResult

    calls: list[str] = []

    def fake_query_database(config: SourceConfig, secrets: dict[str, str]) -> FetchResult:
        calls.append("query_database")
        return FetchResult(rows=[{"id": 1, "status": "open"}], fetched_at="x")

    def fake_run_select(*args: object, **kwargs: object) -> FetchResult:
        calls.append("run_select")
        raise AssertionError("push-down must not run for a raw-SQL tool")

    monkeypatch.setattr(db_connector, "query_database", fake_query_database)
    monkeypatch.setattr(db_connector, "run_select", fake_run_select)

    connector = ConnectorConfig(
        name="Orders",
        slug="orders",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="db",
                name="DB",
                type="postgres",
                url="postgresql://localhost/test",
                table="orders",
                table_name="orders",
            )
        ],
        tools=[
            ToolDefinition(
                id="raw_orders",
                name="Raw orders",
                description="Raw-SQL tool",
                category="READ",
                source_ids=["db"],
                sql='SELECT * FROM "orders"',
            )
        ],
        skills=[],
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})

    assert calls == ["query_database"]
    assert result.rows[0]["status"] == "open"


def test_capped_result_reports_total_and_actionable_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Truncation must be actionable (principle 3): the QueryResult carries the
    true total, and the runtime's note tells the agent the partial-result count
    and the concrete next step."""
    from elliot_connector_runtime.server import _result_truncated, _truncation_note

    monkeypatch.setenv("ELLIOT_MAX_RESULT_ROWS", "3")

    class _StubEngine:
        def query(self, sql: str, params: dict) -> list[dict]:  # type: ignore[type-arg]
            return [{"id": i} for i in range(10)]

    tool = ToolDefinition(
        id="list_things",
        name="List Things",
        description="Return every thing",
        category="READ",
        source_ids=["s"],
        sql="SELECT id FROM things",
        parameters=[],
    )
    executor = ToolExecutor(CONNECTOR, secrets={}, engine=_StubEngine())  # type: ignore[arg-type]

    import asyncio

    result = asyncio.run(executor.execute(tool, {}))

    assert result.truncated is True
    assert len(result.rows) == 3
    assert result.total_rows == 10

    assert _result_truncated(result) is True
    note = _truncation_note(result)
    assert "3 of 10" in note
    assert "narrow" in note.lower()


def test_truncation_note_without_total_is_still_actionable() -> None:
    """A legacy result that flags truncation but carries no total still yields a
    note that names the cap and the next step."""
    from elliot_connector_runtime.server import _truncation_note
    from elliot_core.types import QueryResult

    note = _truncation_note(QueryResult(rows=[], tool_id="t", truncated=True))
    assert "narrow" in note.lower()


def test_source_cap_note_advises_upstream_filtering() -> None:
    """A source-capped result gets distinct advice: the upstream snapshot is
    incomplete, so 'narrow the request' is the WRONG fix — recommend upstream
    filtering/pagination instead."""
    from elliot_connector_runtime.server import _truncation_note
    from elliot_core.types import QueryResult

    note = _truncation_note(
        QueryResult(rows=[{"id": 1}], tool_id="t", truncated=True, truncation_reason="source_cap")
    )
    assert "incomplete" in note.lower()
    assert "upstream" in note.lower()
    # It must NOT tell the agent to merely narrow its own request, which cannot
    # recover rows the source dropped at fetch time.
    assert "narrow the request" not in note.lower()


def test_omitted_param_uses_author_default_in_runtime() -> None:
    """Production must apply an author-declared parameter default just like the
    design-time preview executor does. FastMCP passes an omitted optional param
    through as None; without default-filling, `LIMIT :limit` would bind NULL
    (no limit) instead of the author's default — a preview/production divergence
    and an unbounded over-fetch."""
    import asyncio

    captured: dict = {}

    class _CapturingEngine:
        def query(self, sql: str, params: dict) -> list[dict]:  # type: ignore[type-arg]
            captured.update(params)
            return [{"id": 1}]

    tool = ToolDefinition(
        id="list_things",
        name="List Things",
        description="Return things up to a limit",
        category="READ",
        source_ids=["s"],
        sql="SELECT id FROM things LIMIT :limit",
        parameters=[
            ParameterDefinition(
                name="limit",
                type="integer",
                required=False,
                description="Max rows to return.",
                default=50,
            )
        ],
    )
    executor = ToolExecutor(CONNECTOR, secrets={}, engine=_CapturingEngine())  # type: ignore[arg-type]

    # Agent omits `limit` — FastMCP delivers it as None.
    asyncio.run(executor.execute(tool, {"limit": None}))
    assert captured["limit"] == 50, "author default not applied when param omitted"

    # An explicit value still wins over the default.
    captured.clear()
    asyncio.run(executor.execute(tool, {"limit": 5}))
    assert captured["limit"] == 5


@respx.mock
async def test_executor_write_tool_posts_via_api_mapping() -> None:
    """A published WRITE/ACTION tool must actually execute its mutation: map the
    agent's params into method + path + query + body and POST upstream. Before
    this the runtime advertised the tool but failed the call with 'no sql or
    filter_groups defined' — no published mutation tool could run."""
    from elliot_core.types import ApiRequestMapping

    tool = ToolDefinition(
        id="create_order",
        name="Create Order",
        description="Create a new order for an org",
        category="ACTION",
        source_ids=["api"],
        api_mapping=ApiRequestMapping(
            method="POST",
            path_template="/orgs/{org}/orders",
            query_params=["notify"],
            body_params=["item"],
            body_format="json",
        ),
        parameters=[
            ParameterDefinition(name="org", type="string", required=True, description="org slug"),
            ParameterDefinition(name="item", type="string", required=True, description="item"),
            ParameterDefinition(
                name="notify", type="boolean", required=False, description="notify"
            ),
        ],
    )
    connector = ConnectorConfig(
        name="Shop",
        slug="shop",
        version="1.0.0",
        sources=[SourceConfig(id="api", name="API", type="rest", url="https://api.example.com")],
        tools=[tool],
        skills=[],
    )
    route = respx.post("https://api.example.com/orgs/acme/orders").mock(
        return_value=httpx.Response(201, json={"id": 7, "item": "widget"})
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(tool, {"org": "acme", "item": "widget", "notify": True})

    assert result.rows == [{"id": 7, "item": "widget"}]
    req = route.calls.last.request
    assert req.method == "POST"
    # Path placeholder substituted; query + JSON body carried through.
    assert "notify=true" in str(req.url)
    import json as _json

    assert _json.loads(req.content) == {"item": "widget"}


@respx.mock
async def test_executor_write_tool_multi_credential_headers_and_static_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A WRITE tool against a session API: the bearer auth header, the source's
    extra credential headers (ecomtoken/cookie), and its static body all reach
    the upstream alongside the mapped body params (the cart-write case)."""
    import json as _json

    from elliot_core.types import ApiRequestMapping, AuthConfig

    monkeypatch.setenv("BEARER", "btok")
    monkeypatch.setenv("ECOMTOKEN", "etok")
    tool = ToolDefinition(
        id="write_cart",
        name="Write cart",
        description="Add items to the user's cart.",
        category="WRITE",
        source_ids=["api"],
        api_mapping=ApiRequestMapping(
            method="POST", path_template="/cart", body_params=["items"], body_format="json"
        ),
        parameters=[
            ParameterDefinition(name="items", type="object", required=True, description="map"),
        ],
    )
    connector = ConnectorConfig(
        name="Cart",
        slug="cart",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="api",
                name="API",
                type="rest",
                url="https://api.example.com",
                auth=AuthConfig(type="bearer", secret_key="{{ env:BEARER }}"),
                headers={"ecomtoken": "{{ env:ECOMTOKEN }}", "cookie": "sid=1"},
                body={"store": "331", "isClub": 0},
            )
        ],
        tools=[tool],
        skills=[],
    )
    route = respx.post("https://api.example.com/cart").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    executor = ToolExecutor(connector, secrets={})
    await executor.execute(tool, {"items": {"123": "2"}})

    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer btok"
    assert req.headers["ecomtoken"] == "etok"
    assert req.headers["cookie"] == "sid=1"
    # Static source body merged under the mapped dynamic-key items map.
    assert _json.loads(req.content) == {"store": "331", "isClub": 0, "items": {"123": "2"}}


@respx.mock
async def test_executor_write_tool_surfaces_http_status() -> None:
    """An upstream error becomes an actionable API_REQUEST_FAILED carrying the
    status code — not a raw stack trace, and not a silent success."""
    from elliot_core.errors import ElliotError
    from elliot_core.types import ApiRequestMapping

    tool = ToolDefinition(
        id="delete_order",
        name="Delete Order",
        description="Delete an order by id",
        category="ACTION",
        source_ids=["api"],
        api_mapping=ApiRequestMapping(method="DELETE", path_template="/orders/{order_id}"),
        parameters=[
            ParameterDefinition(name="order_id", type="string", required=True, description="id")
        ],
    )
    connector = ConnectorConfig(
        name="Shop",
        slug="shop",
        version="1.0.0",
        sources=[SourceConfig(id="api", name="API", type="rest", url="https://api.example.com")],
        tools=[tool],
        skills=[],
    )
    respx.delete("https://api.example.com/orders/abc").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    executor = ToolExecutor(connector, secrets={})
    with pytest.raises(ElliotError) as exc_info:
        await executor.execute(tool, {"order_id": "abc"})
    assert exc_info.value.code == "API_REQUEST_FAILED"
    assert exc_info.value.detail["status_code"] == 404
    # The message carries actionable, status-specific recovery guidance (a 404 =
    # bad id), not just the bare status — and never the upstream body.
    assert "not found" in exc_info.value.message.lower()
    assert "not found" not in str(exc_info.value.detail)  # body not echoed


def test_http_status_guidance_is_actionable_per_status_class() -> None:
    from elliot_connector_runtime.executor import _http_status_guidance

    assert "parameter schema" in _http_status_guidance(422)
    assert "configuration issue" in _http_status_guidance(401)
    assert "not found" in _http_status_guidance(404)
    assert "Conflict" in _http_status_guidance(409)
    assert "rate-limiting" in _http_status_guidance(429)
    assert "server error" in _http_status_guidance(503)


@respx.mock
async def test_executor_write_tool_handles_no_content() -> None:
    """A 204 No Content mutation reports a compact success row instead of
    failing on an empty JSON body."""
    from elliot_core.types import ApiRequestMapping

    tool = ToolDefinition(
        id="archive_order",
        name="Archive Order",
        description="Archive an order by id",
        category="ACTION",
        source_ids=["api"],
        api_mapping=ApiRequestMapping(method="POST", path_template="/orders/{order_id}/archive"),
        parameters=[
            ParameterDefinition(name="order_id", type="string", required=True, description="id")
        ],
    )
    connector = ConnectorConfig(
        name="Shop",
        slug="shop",
        version="1.0.0",
        sources=[SourceConfig(id="api", name="API", type="rest", url="https://api.example.com")],
        tools=[tool],
        skills=[],
    )
    respx.post("https://api.example.com/orders/abc/archive").mock(return_value=httpx.Response(204))
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(tool, {"order_id": "abc"})
    assert result.rows == [{"ok": True, "status_code": 204}]


@pytest.mark.asyncio
@respx.mock
async def test_passthrough_error_reports_constructed_url_at_runtime() -> None:
    # P2-c (runtime path): a failed passthrough call must name the resource the
    # caller actually requested, not the base source's baked-in resource_id.
    from elliot_core.errors import ElliotError

    connector = ConnectorConfig(
        name="DataStore",
        slug="datastore",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="search",
                name="Search",
                type="rest",
                url="https://api.example.com/search?resource_id=BAKED-05d14adb&limit=100",
            )
        ],
        tools=[
            ToolDefinition(
                id="datastore_query",
                name="Datastore query",
                description="Query a datastore resource live.",
                category="READ",
                source_ids=["search"],
                rest_query_params=["resource_id"],
                parameters=[
                    ParameterDefinition(
                        name="resource_id", type="string", required=True, description="resource id"
                    )
                ],
            )
        ],
        skills=[],
    )
    respx.get("https://api.example.com/search").mock(return_value=httpx.Response(404))
    executor = ToolExecutor(connector, secrets={})

    with pytest.raises(ElliotError) as excinfo:
        await executor.execute(connector.tools[0], {"resource_id": "totally-bogus-id-xyz"})

    exc = excinfo.value
    assert exc.code == "UPSTREAM_FETCH_FAILED"
    assert "totally-bogus-id-xyz" in exc.message
    assert "BAKED-05d14adb" not in exc.message


@pytest.mark.asyncio
@respx.mock
async def test_executor_odata_pagination_follows_next_link() -> None:
    # Parity with design-time api_fetcher: a published OData connector must
    # follow @odata.nextLink instead of capping at the first page.
    connector = ConnectorConfig(
        name="OData",
        slug="odata",
        version="1.0.0",
        sources=[
            SourceConfig(
                id="things",
                name="Things",
                type="rest",
                url="https://api.example.com/Things",
                data_path="value",
                table_name="things",
                pagination=PaginationConfig(strategy="odata", max_pages=10),
            )
        ],
        tools=[
            ToolDefinition(
                id="list_things",
                name="List things",
                description="List things from the OData feed.",
                category="READ",
                source_ids=["things"],
                sql="SELECT id FROM things",
            )
        ],
        skills=[],
    )
    respx.get("https://api.example.com/Things").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "value": [{"id": 1}, {"id": 2}],
                    "@odata.nextLink": "https://api.example.com/Things?$skiptoken=2",
                },
            ),
            httpx.Response(200, json={"value": [{"id": 3}]}),
        ]
    )
    executor = ToolExecutor(connector, secrets={})
    result = await executor.execute(connector.tools[0], {})
    assert sorted(r["id"] for r in result.rows) == [1, 2, 3]


def test_skill_payload_omits_primary_and_counts_retained_step_rows() -> None:
    """A skill payload is token-lean: the final step is `rows` and is NOT
    duplicated under `steps`; estimated_tokens counts the final rows AND the
    retained earlier-step rows, so the reported cost matches what's on the wire."""
    from elliot_connector_runtime.server import _payload_for, _skill_payload
    from elliot_core.types import ToolResult

    result = ToolResult(
        rows=[{"order_count": 3}],
        meta={
            "primary_step": "o",
            "step_count": 2,
            "steps": {
                "u": {"rows": [{"id": 42, "email": "a@b.com"}], "row_count": 1, "meta": {}},
                "o": {"rows": [{"order_count": 3}], "row_count": 1, "meta": {}},
            },
        },
    )
    payload = _skill_payload(result)
    assert payload["rows"] == [{"order_count": 3}]
    assert payload["primary_step"] == "o"
    # The primary step is not repeated under `steps` — only the earlier one.
    assert set(payload["steps"]) == {"u"}
    # Honest accounting: more than the final step alone (which the base payload
    # would report), because the retained `u` rows are on the wire too.
    final_only = _payload_for(ToolResult(rows=[{"order_count": 3}], meta={}))["estimated_tokens"]
    assert payload["estimated_tokens"] > final_only


def test_single_step_skill_payload_has_no_steps_key() -> None:
    """A one-step skill's only result is the answer — no redundant `steps`."""
    from elliot_connector_runtime.server import _skill_payload
    from elliot_core.types import ToolResult

    result = ToolResult(
        rows=[{"id": 7}],
        meta={
            "primary_step": "only",
            "step_count": 1,
            "steps": {"only": {"rows": [{"id": 7}], "row_count": 1, "meta": {}}},
        },
    )
    payload = _skill_payload(result)
    assert payload["rows"] == [{"id": 7}]
    assert "steps" not in payload
