"""Benchmark: token cost of a raw JSON API vs an Elliot connector.

Generates one very large synthetic e-commerce API response, then measures how
many tokens each of three strategies burns into an agent's context window to
answer a single analytical question:

    "What is the combined lifetime value of every enterprise-tier customer
     based in Germany, and who are they?"

Strategies compared
  1. raw-dump   The whole API response is handed back as a tool result and
                lands, unprocessed, in the agent's context window. This is
                what wiring a REST API straight into an MCP tool produces.
  2. code-exec  An agent with a code-execution sandbox. The file never enters
                the context window, but the agent must still discover the
                schema (it prints a sample of records) and the printed answer
                round-trips through the context.
  3. elliot     An Elliot READ tool runs the filter / aggregation server-side
                (fetch -> SQLite -> generated SELECT) and returns only the
                shaped rows the question actually needs.

Token counts use the same ~4-chars-per-token heuristic as
``elliot_core.eval_runner`` so the numbers line up with Elliot's own eval
output. Run with:

    uv run python benchmarks/json_token_usage.py
    uv run python benchmarks/json_token_usage.py --customers 6000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import shutil
import tempfile
from pathlib import Path
from typing import Any

from elliot_core.tools.executor import ToolExecutor
from elliot_core.types.connector import ConnectorConfig
from elliot_core.types.source import SourceConfig
from elliot_core.types.tool import (
    FilterCondition,
    FilterGroup,
    OrderField,
    ResponseShape,
    ReturnField,
    ToolDefinition,
    ToolResult,
)

FIRST_NAMES = [
    "Anna",
    "Lukas",
    "Marie",
    "Felix",
    "Sophie",
    "Jonas",
    "Emma",
    "Paul",
    "Laura",
    "Max",
    "Hannah",
    "Leon",
    "Mia",
    "Noah",
    "Lena",
    "Elias",
]
LAST_NAMES = [
    "Müller",
    "Schmidt",
    "Schneider",
    "Fischer",
    "Weber",
    "Meyer",
    "Wagner",
    "Becker",
    "Hoffmann",
    "Koch",
    "Bauer",
    "Richter",
    "Klein",
    "Wolf",
]
COUNTRIES = ["US", "DE", "GB", "FR", "JP", "CA", "AU", "BR", "IN", "NL"]
TIERS = ["free", "pro", "enterprise"]
TIER_WEIGHTS = [55, 33, 12]
ORDER_STATUSES = ["completed", "refunded", "pending", "cancelled"]

DATA_FILENAME = "customers_api.json"

# The exploration snippet a code-execution agent runs first, before it can
# write a correct filter — it does not know the schema up front.
EXPLORE_CODE = """import json
data = json.load(open("customers_api.json"))
print(list(data.keys()))
print(data["meta"])
print(json.dumps(data["data"][:2], indent=2))"""

# The filter snippet the agent runs once it has seen the schema.
FILTER_CODE = """hits = [c for c in data["data"]
        if c["tier"] == "enterprise" and c["country"] == "DE"]
hits.sort(key=lambda c: c["lifetime_value"], reverse=True)
for c in hits:
    print(c["name"], c["lifetime_value"])
print("TOTAL", round(sum(c["lifetime_value"] for c in hits), 2))"""


def est_tokens(obj: Any) -> int:
    """Estimate token count with the ~4-chars-per-token heuristic.

    Identical to the estimator in ``elliot_core.eval_runner``, so results
    here are directly comparable to Elliot's eval output.
    """
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return max(1, len(text) // 4)


def _rand_date(rng: random.Random) -> str:
    return f"20{rng.randint(20, 25):02d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"


def _make_order(rng: random.Random, cust_idx: int, j: int) -> dict[str, Any]:
    return {
        "order_id": f"ORD-{cust_idx:06d}-{j:03d}",
        "date": _rand_date(rng),
        "amount": round(rng.uniform(9.99, 899.99), 2),
        "status": rng.choice(ORDER_STATUSES),
        "item_count": rng.randint(1, 8),
    }


def _make_customer(rng: random.Random, idx: int) -> dict[str, Any]:
    orders = [_make_order(rng, idx, j) for j in range(rng.randint(3, 45))]
    return {
        "customer_id": f"CUST-{idx:06d}",
        "name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        "email": f"user{idx}@example.com",
        "tier": rng.choices(TIERS, weights=TIER_WEIGHTS)[0],
        "country": rng.choice(COUNTRIES),
        "signup_date": _rand_date(rng),
        "active": rng.random() > 0.15,
        "lifetime_value": round(sum(o["amount"] for o in orders), 2),
        "orders": orders,
    }


def generate_api_response(n_customers: int, seed: int = 42) -> dict[str, Any]:
    """Build a realistic, deeply nested e-commerce API response."""
    rng = random.Random(seed)
    customers = [_make_customer(rng, i) for i in range(1, n_customers + 1)]
    return {
        "meta": {
            "api_version": "2.4.1",
            "endpoint": "/v2/customers",
            "generated_at": "2026-05-19T00:00:00Z",
            "total": len(customers),
            "page": 1,
            "per_page": len(customers),
        },
        "data": customers,
    }


def build_connector(data_path: Path) -> ConnectorConfig:
    """An Elliot connector with two READ tools over the generated file."""
    source = SourceConfig(
        id="customers",
        name="Customers API snapshot",
        type="file",
        path=str(data_path),
        format="json",
    )
    enterprise_de = FilterGroup(
        logic="AND",
        conditions=[
            FilterCondition(field="tier", operator="=", value="enterprise"),
            FilterCondition(field="country", operator="=", value="DE"),
        ],
    )
    list_tool = ToolDefinition(
        id="list_enterprise_customers_de",
        name="List enterprise customers in Germany",
        description=(
            "List enterprise-tier customers based in Germany with each "
            "customer's name and lifetime value, highest value first."
        ),
        category="READ",
        source_ids=["customers"],
        filter_groups=[enterprise_de],
        return_fields=[
            ReturnField(field="name"),
            ReturnField(field="country"),
            ReturnField(field="lifetime_value"),
        ],
        order_by=[OrderField(field="lifetime_value", direction="DESC")],
        limit=500,
        response_shape=ResponseShape(max_rows=500),
    )
    agg_tool = ToolDefinition(
        id="total_value_enterprise_de",
        name="Total lifetime value of enterprise customers in Germany",
        description=(
            "Return the combined lifetime value and head count of all "
            "enterprise-tier customers based in Germany."
        ),
        category="READ",
        source_ids=["customers"],
        filter_groups=[enterprise_de],
        return_fields=[
            ReturnField(field="lifetime_value", aggregation="sum", alias="total_lifetime_value"),
            ReturnField(field="customer_id", aggregation="count", alias="customer_count"),
        ],
        limit=1,
        response_shape=ResponseShape(max_rows=1),
    )
    return ConnectorConfig(
        name="Customers Benchmark Connector",
        slug="customers-benchmark",
        version="1.0.0",
        sources=[source],
        tools=[list_tool, agg_tool],
    )


async def run_elliot(connector: ConnectorConfig) -> tuple[ToolResult, ToolResult]:
    """Execute both Elliot READ tools against the generated file."""
    executor = ToolExecutor(connector)
    list_result = await executor.execute("list_enterprise_customers_de", {})
    agg_result = await executor.execute("total_value_enterprise_de", {})
    return list_result, agg_result


def _bar(value: int, max_value: int, width: int = 46) -> str:
    """A log-scaled ASCII bar — the raw-dump value dwarfs the others linearly."""
    if value <= 0:
        return ""
    frac = math.log10(value + 1) / math.log10(max_value + 1)
    return "#" * max(1, int(frac * width))


def _fmt_ctx(tokens: int, window: int = 200_000) -> str:
    if tokens <= window:
        return "fits"
    return f"NO ({tokens / window:.1f}x over)"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--customers", type=int, default=3000, help="number of customer records to generate"
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible data")
    parser.add_argument(
        "--keep", action="store_true", help="keep the generated data directory on disk"
    )
    args = parser.parse_args()

    data_dir = Path(tempfile.mkdtemp(prefix="elliot-bench-"))
    # file_reader confines file: sources to ELLIOT_FILE_ROOT; point it at the
    # temp dir so the connector can read the generated snapshot.
    os.environ["ELLIOT_FILE_ROOT"] = str(data_dir)
    data_path = data_dir / DATA_FILENAME

    try:
        print(f"Generating {args.customers:,} customers ...")
        full = generate_api_response(args.customers, seed=args.seed)
        payload = json.dumps(full)
        data_path.write_text(payload)

        n_orders = sum(len(c["orders"]) for c in full["data"])
        size_mb = len(payload) / 1_048_576

        # Ground truth — also the answer a perfect agent would produce.
        hits = [c for c in full["data"] if c["tier"] == "enterprise" and c["country"] == "DE"]
        hits.sort(key=lambda c: c["lifetime_value"], reverse=True)
        total_ltv = round(sum(c["lifetime_value"] for c in hits), 2)

        # ── Strategy 1: raw dump ────────────────────────────────────────────
        raw_tokens = est_tokens(payload)

        # ── Strategy 2: code execution ──────────────────────────────────────
        # Schema discovery output: keys + meta + first two full records.
        explore_out = (
            f"{list(full.keys())}\n"
            f"{json.dumps(full['meta'])}\n"
            f"{json.dumps(full['data'][:2], indent=2)}"
        )
        answer = "\n".join(f"{c['name']}\t{c['lifetime_value']}" for c in hits)
        answer += f"\nTOTAL\t{total_ltv}"
        codeexec_tokens = (
            est_tokens(EXPLORE_CODE)
            + est_tokens(explore_out)
            + est_tokens(FILTER_CODE)
            + est_tokens(answer)
        )

        # ── Strategy 3: Elliot connector ────────────────────────────────────
        connector = build_connector(data_path)
        list_result, agg_result = asyncio.run(run_elliot(connector))
        elliot_tokens = est_tokens(list_result.model_dump())
        agg_tokens = est_tokens(agg_result.model_dump())
        tool_defs_tokens = est_tokens([t.model_dump() for t in connector.tools])

        # ── Report ──────────────────────────────────────────────────────────
        line = "=" * 68
        print()
        print(line)
        print("  ELLIOT BENCHMARK  —  JSON API token cost")
        print(line)
        print("Dataset")
        print(f"  customers .............. {args.customers:,}")
        print(f"  orders ................. {n_orders:,}")
        print(f"  API response size ...... {size_mb:.2f} MB")
        print('  question ............... "Combined lifetime value of every')
        print('                            enterprise-tier customer in Germany?"')
        print(f"  answer ................. {len(hits)} customers, ${total_ltv:,.2f} total")
        print()

        rows = [
            ("raw-dump", raw_tokens),
            ("code-exec", codeexec_tokens),
            ("elliot", elliot_tokens),
        ]
        max_tokens = max(t for _, t in rows)
        print("Token cost per strategy  (lower is better)")
        print("-" * 68)
        print(f"  {'strategy':<11} {'tokens':>12}   {'200K context':<16} {'vs elliot':>10}")
        print("-" * 68)
        for name, tokens in rows:
            ratio = tokens / elliot_tokens
            ratio_str = "baseline" if name == "elliot" else f"{ratio:,.0f}x more"
            print(f"  {name:<11} {tokens:>12,}   {_fmt_ctx(tokens):<16} {ratio_str:>10}")
        print("-" * 68)
        for name, tokens in rows:
            print(f"  {name:<11} | {_bar(tokens, max_tokens)}")
        print("-" * 68)
        print("  (bars are log-scaled — raw-dump dwarfs the rest linearly)")
        print()

        print("What each strategy puts in the context window")
        print(f"  raw-dump   the entire {size_mb:.1f} MB response, unprocessed")
        print("  code-exec  schema-discovery sample + filter code + printed answer")
        print(f"  elliot     {len(list_result.rows)} shaped rows from a server-side SELECT")
        print()
        print("Elliot can also do the math server-side:")
        print(
            f"  total_value_enterprise_de -> {len(agg_result.rows)} row, "
            f"{agg_tokens} tokens: {agg_result.rows}"
        )
        print(
            f"  (one-time tool-definition overhead for both Elliot tools: "
            f"{tool_defs_tokens:,} tokens)"
        )
        print()

        savings = (1 - elliot_tokens / raw_tokens) * 100
        print(
            f"Bottom line: Elliot answers the question in {elliot_tokens:,} tokens — "
            f"{raw_tokens / elliot_tokens:,.0f}x fewer than dumping the raw API "
            f"({savings:.2f}% saved)"
        )
        print(
            f"             and {codeexec_tokens / elliot_tokens:,.1f}x fewer than a "
            f"code-execution agent that still pays for schema discovery."
        )
        print(line)

        if args.keep:
            print(f"\nGenerated data kept at: {data_path}")
    finally:
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
