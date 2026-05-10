"""Elliot CLI — lint, eval, init, and status subcommands."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elliot_core.types import ConnectorConfig

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_TEMPLATE_DESCRIPTIONS = {
    "rest-api-key": "REST API with API key header auth",
    "postgres-readonly": "PostgreSQL read-only connector",
    "paginated-rest": "REST API with cursor/offset pagination",
    "openapi-petstore": "Full Petstore example (docs/tutorials)",
}


def _load_connector(path: str | Path) -> ConnectorConfig:  # noqa: F821
    from elliot_core.connector.serializer import deserialize_connector

    p = Path(path)
    if not p.exists():
        print(f"Error: connector file not found: {p}", file=sys.stderr)
        sys.exit(1)
    return deserialize_connector(p.read_text(encoding="utf-8"))


def _cmd_lint(args: argparse.Namespace) -> None:
    from elliot_core.linter import lint_connector

    config = _load_connector(args.path)
    issues = lint_connector(config)

    errors = [i for i in issues if i.severity == "ERROR"]
    warns = [i for i in issues if i.severity == "WARN"]
    infos = [i for i in issues if i.severity == "INFO"]

    for issue in issues:
        icon = {"ERROR": "X", "WARN": "!", "INFO": "i"}[issue.severity]
        tool = f"[{issue.tool_id}]" if issue.tool_id else "[connector]"
        print(f"[{icon}] {issue.severity:<5} {tool:<20} {issue.code}")
        print(f"      {issue.message}")
        print(f"      Fix: {issue.suggestion}\n")

    total = len(issues)
    print(f"{total} issue(s): {len(errors)} errors, {len(warns)} warnings, {len(infos)} info")
    sys.exit(1 if errors else 0)


def _cmd_eval(args: argparse.Namespace) -> None:
    import asyncio

    from elliot_core.eval_types import load_eval_suite

    suite = load_eval_suite(args.path)

    connector_path = args.connector or (
        Path(args.path).parent / f"{suite.connector}.connector.json"
    )
    config = _load_connector(connector_path)

    from elliot_core.eval_runner import EvalRunner

    runner = EvalRunner(config)
    results = asyncio.run(runner.run_suite(suite))

    passed = sum(1 for r in results if r.passed)
    for r in results:
        icon = "OK" if r.passed else "FAIL"
        token_warn = " [large]" if r.token_estimate > 500 else ""
        print(
            f"[{icon}]  {r.case_id:<35} {r.result_rows} rows  "
            f"{r.token_estimate} tokens  {r.duration_ms}ms{token_warn}"
        )
        for fail in r.failures:
            print(f"       - {fail}")

    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


def _cmd_init(args: argparse.Namespace) -> None:
    if args.list:
        print("Available templates:")
        for name, desc in _TEMPLATE_DESCRIPTIONS.items():
            print(f"  {name:<25} {desc}")
        return

    if not args.template:
        print("Error: provide --template NAME or --list", file=sys.stderr)
        sys.exit(1)

    src = _TEMPLATES_DIR / f"{args.template}.connector.json"
    if not src.exists():
        print(
            f"Error: unknown template '{args.template}'. Run: elliot init --list", file=sys.stderr
        )
        sys.exit(1)

    dest = Path(args.output or f"{args.template}.connector.json")
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Created {dest}")
    print(f"Next: elliot lint {dest}")


def _cmd_status(args: argparse.Namespace) -> None:
    import httpx

    plugin_url = os.environ.get("ELLIOT_PLUGIN_URL", "http://localhost:3000")
    runtime_url = os.environ.get("ELLIOT_RUNTIME_URL", "http://localhost:3001")
    studio_url = os.environ.get("ELLIOT_STUDIO_URL", "http://localhost:5173")
    db_url = os.environ.get("ELLIOT_DB_URL", "sqlite:///.elliot/observations.db")

    results: list[tuple[str, str, bool, str]] = []

    for name, url, detail_path in [
        ("plugin", plugin_url, "/health"),
        ("runtime", runtime_url, "/health"),
        ("studio", studio_url, None),
    ]:
        try:
            path = detail_path or "/"
            r = httpx.get(f"{url}{path}", timeout=3)
            detail = ""
            if r.status_code == 200 and detail_path:
                data = r.json()
                if name == "runtime":
                    connector = data.get("connector", "")
                    detail = f"  connector: {connector}" if connector else ""
            results.append((name, url, True, detail))
        except Exception:
            results.append((name, url, False, ""))

    try:
        from elliot_connector_runtime.observation_store import ObservationStore

        store = ObservationStore(db_url)
        count = len(store.recent_tool_calls(10000))
        results.append(("database", db_url, True, f"  {count} tool calls"))
    except Exception:
        results.append(("database", db_url, False, ""))

    print("\nElliot Services")
    print("─" * 56)
    all_ok = True
    for name, url, ok, detail in results:
        icon = "✓" if ok else "✗"
        state = "running" if ok else "not reachable"
        print(f"  {name:<10} {url:<35} {icon} {state}{detail}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  All services healthy.")
    else:
        failed = sum(1 for _, _, ok, _ in results if not ok)
        print(f"  {failed} service(s) not reachable. Is honcho running? Try: honcho start")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="elliot", description="Elliot developer tools")
    sub = parser.add_subparsers(dest="command")

    lint_cmd = sub.add_parser("lint", help="Check a connector file for agent-readiness")
    lint_cmd.add_argument("path", help="Path to .connector.json")

    eval_cmd = sub.add_parser("eval", help="Run evaluation cases against a connector")
    eval_cmd.add_argument("path", help="Path to .eval.yaml")
    eval_cmd.add_argument("--connector", help="Override connector .json path")

    init_cmd = sub.add_parser("init", help="Create a connector from a starter template")
    init_cmd.add_argument("--template", help="Template name (see --list)")
    init_cmd.add_argument("--list", action="store_true", help="Show available templates")
    init_cmd.add_argument("output", nargs="?", help="Output filename")

    sub.add_parser("status", help="Show running status of all Elliot services")

    args = parser.parse_args()

    if args.command == "lint":
        _cmd_lint(args)
    elif args.command == "eval":
        _cmd_eval(args)
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "status":
        _cmd_status(args)
    else:
        parser.print_help()
        sys.exit(1)
