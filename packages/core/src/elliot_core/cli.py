"""Elliot CLI — lint and eval subcommands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from elliot_core.types import ConnectorConfig


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


def main() -> None:
    parser = argparse.ArgumentParser(prog="elliot", description="Elliot developer tools")
    sub = parser.add_subparsers(dest="command")

    lint_cmd = sub.add_parser("lint", help="Check a connector file for agent-readiness")
    lint_cmd.add_argument("path", help="Path to .connector.json")

    eval_cmd = sub.add_parser("eval", help="Run evaluation cases against a connector")
    eval_cmd.add_argument("path", help="Path to .eval.yaml")
    eval_cmd.add_argument("--connector", help="Override connector .json path")

    args = parser.parse_args()

    if args.command == "lint":
        _cmd_lint(args)
    elif args.command == "eval":
        _cmd_eval(args)
    else:
        parser.print_help()
        sys.exit(1)
