"""A source that acts as the signed-in caller is never shared between callers.

Snapshot READ tools normally load a source once into an engine every caller
queries. With ``{{ caller:... }}`` credentials that engine would hand the
first caller's data to everyone, so these sources are fetched per call.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from elliot_connector_runtime.executor import ExecutorError, ToolExecutor
from elliot_core.caller import CallerCredentialMissingError, caller_credentials
from elliot_core.types import (
    AuthConfig,
    ConnectorConfig,
    ParameterDefinition,
    SourceConfig,
    ToolDefinition,
)

CONNECTOR = ConnectorConfig(
    name="Orders",
    slug="orders",
    version="1.0.0",
    sources=[
        SourceConfig(
            id="orders",
            name="My orders",
            type="rest",
            url="https://api.example.com/me/orders",
            table_name="orders",
            auth=AuthConfig(type="bearer", secret_key="{{ caller:token }}"),
            headers={"X-Acme-User": "{{ caller:sub }}"},
        )
    ],
    tools=[
        ToolDefinition(
            id="list_my_orders",
            name="List my orders",
            description="List the signed-in user's orders, newest first.",
            category="READ",
            source_ids=["orders"],
            sql="SELECT id, total FROM orders WHERE total >= :min_total ORDER BY id DESC",
            parameters=[
                ParameterDefinition(
                    name="min_total", type="number", description="Smallest total", default=0
                )
            ],
        )
    ],
    skills=[],
)


def _orders_for(request: httpx.Request) -> httpx.Response:
    user = request.headers.get("X-Acme-User")
    data = {"alice": [{"id": 1, "total": 10}], "bob": [{"id": 7, "total": 99}]}
    return httpx.Response(200, json=data.get(user or "", []))


@respx.mock
async def test_each_caller_gets_only_their_own_rows() -> None:
    route = respx.get("https://api.example.com/me/orders").mock(side_effect=_orders_for)
    executor = ToolExecutor(CONNECTOR, secrets={})
    tool = CONNECTOR.tools[0]

    with caller_credentials({"token": "tok-alice", "sub": "alice"}):
        alice = await executor.execute(tool, {})
    with caller_credentials({"token": "tok-bob", "sub": "bob"}):
        bob = await executor.execute(tool, {})

    assert alice.rows == [{"id": 1, "total": 10}]
    assert bob.rows == [{"id": 7, "total": 99}], "bob was served alice's cached snapshot"
    sent = [c.request for c in route.calls]
    assert [r.headers["Authorization"] for r in sent] == ["Bearer tok-alice", "Bearer tok-bob"]
    assert executor._engine is None, "a per-caller source reached the shared engine"


@respx.mock
async def test_a_call_with_no_signed_in_caller_is_refused() -> None:
    route = respx.get("https://api.example.com/me/orders").mock(
        return_value=httpx.Response(200, json=[])
    )
    executor = ToolExecutor(CONNECTOR, secrets={"CALLER_TOKEN": "owner-test-token"})

    with pytest.raises(CallerCredentialMissingError):
        await executor.execute(CONNECTOR.tools[0], {})
    assert not route.called, "the runtime fell back to a saved test credential"


async def test_the_shared_engine_refuses_a_per_caller_source() -> None:
    executor = ToolExecutor(CONNECTOR, secrets={})
    with pytest.raises(ExecutorError, match="acts as the caller"):
        await executor._ensure_materialized(CONNECTOR.tools[0], {})
