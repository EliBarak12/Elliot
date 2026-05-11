"""Elliot CLI — lint, eval, init, status, and connect subcommands."""

from __future__ import annotations

import argparse
import json
import os
import shutil
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


def _write_json_merge(path: Path, key: str, entry_key: str, entry_value: object) -> bool:
    """Merge {key: {entry_key: entry_value}} into a JSON file. Returns True if changed."""
    data: dict[str, dict[str, object]] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except json.JSONDecodeError:
            pass
    servers = data.setdefault(key, {})
    if servers.get(entry_key) == entry_value:
        return False
    servers[entry_key] = entry_value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _cmd_connect(args: argparse.Namespace) -> None:
    """Register Elliot MCP server with every AI coding agent found on this machine."""
    cwd = Path.cwd()
    home = Path.home()
    plugin_url = os.environ.get("ELLIOT_PLUGIN_URL", "http://localhost:3000")
    mcp_url = f"{plugin_url}/mcp"

    results: list[tuple[str, Path, str]] = []  # (agent, path, status)

    # ── Claude Code ────────────────────────────────────────────────────────
    # .mcp.json in project root; also write if claude binary exists globally
    claude_config = cwd / ".mcp.json"
    entry = {"type": "http", "url": mcp_url}
    changed = _write_json_merge(claude_config, "mcpServers", "elliot", entry)
    results.append(("Claude Code", claude_config, "updated" if changed else "already configured"))

    # ── VS Code / GitHub Copilot ───────────────────────────────────────────
    if shutil.which("code") or (cwd / ".vscode").exists():
        vscode_config = cwd / ".vscode" / "mcp.json"
        vs_entry = {"type": "http", "url": mcp_url}
        changed = _write_json_merge(vscode_config, "servers", "elliot", vs_entry)
        results.append(
            ("VS Code / Copilot", vscode_config, "updated" if changed else "already configured")
        )

    # ── Cursor ─────────────────────────────────────────────────────────────
    if shutil.which("cursor") or (home / ".cursor").exists() or (cwd / ".cursor").exists():
        cursor_config = cwd / ".cursor" / "mcp.json"
        cursor_entry = {"type": "http", "url": mcp_url}
        changed = _write_json_merge(cursor_config, "mcpServers", "elliot", cursor_entry)
        results.append(("Cursor", cursor_config, "updated" if changed else "already configured"))

    # ── Windsurf ───────────────────────────────────────────────────────────
    windsurf_dir = home / ".codeium" / "windsurf"
    if windsurf_dir.exists():
        windsurf_config = windsurf_dir / "mcp_config.json"
        ws_entry = {"serverUrl": mcp_url}
        changed = _write_json_merge(windsurf_config, "mcpServers", "elliot", ws_entry)
        results.append(
            ("Windsurf", windsurf_config, "updated" if changed else "already configured")
        )

    print("\nElliot MCP Connect")
    print("─" * 60)
    print(f"  MCP server: {mcp_url}\n")

    for agent, path, status in results:
        icon = "✓" if "configured" in status else "+"
        print(f"  {icon} {agent:<22} {status}")
        print(f"    └ {path}")

    if not results:
        print("  No supported agents detected.")
        print("  Supported: Claude Code, VS Code/Copilot, Cursor, Windsurf")

    print()
    print("  Next steps:")
    print("  1. Start Elliot:          honcho start")
    print("  2. Reload your agent      (restart or run /reconnect-mcp)")
    print("  3. Ask your agent:        'I have an API at https://... — help me build a connector'")
    print()


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
    sub.add_parser(
        "connect",
        help="Register Elliot MCP server with Claude Code, Cursor, VS Code, and Windsurf",
    )

    args = parser.parse_args()

    if args.command == "lint":
        _cmd_lint(args)
    elif args.command == "eval":
        _cmd_eval(args)
    elif args.command == "init":
        _cmd_init(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "connect":
        _cmd_connect(args)
    else:
        parser.print_help()
        sys.exit(1)
