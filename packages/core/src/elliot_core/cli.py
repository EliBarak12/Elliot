"""Elliot CLI — lint, eval, init, status, and connect subcommands."""

from __future__ import annotations

import argparse
import json
import os
import re
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


def _codex_section_re(section: str) -> re.Pattern[str]:
    return re.compile(rf"(?ms)^\[mcp_servers\.{re.escape(section)}\]\n.*?(?=^\[|\Z)")


def _write_codex_toml(path: Path, url: str, section: str = "elliot") -> bool:
    """Write [mcp_servers.<section>] into a Codex config.toml. Returns True if changed."""
    desired = f'[mcp_servers.{section}]\nurl = "{url}"\n'
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if desired in existing:
        return False
    section_re = _codex_section_re(section)
    if section_re.search(existing):
        new_content = section_re.sub(desired, existing, count=1)
    else:
        sep = "\n" if existing and not existing.endswith("\n") else ""
        gap = "\n" if existing else ""
        new_content = existing + sep + gap + desired
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")
    return True


def _probe_mcp_initialize(url: str, timeout: float = 2.0) -> tuple[bool, str | None]:
    """POST a JSON-RPC `initialize` and confirm a JSON-RPC reply.

    Returns (ok, reason). Used to verify a URL is actually MCP-speakable
    before we write it into an agent's config.
    """
    import json as _json
    import urllib.error
    import urllib.request

    body = _json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "elliot-connect-probe", "version": "0.1.0"},
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        # nosec - URL is operator-supplied (resolved from ELLIOT_*_URL env or
        # the local default). The CLI legitimately probes localhost, so this
        # path bypasses the SSRF validator.
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read(8192).decode("utf-8", errors="replace")
            if "jsonrpc" in raw or resp.status in (200, 202):
                return True, None
            return False, f"non-MCP response: HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        # FastMCP returns 400 on a probe-without-sessionid; that still proves
        # the endpoint is MCP-speaking, just rejecting the probe payload.
        if exc.code in (400, 405):
            return True, None
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        return False, str(exc)


def _register_for_all_agents(
    label: str,
    mcp_url: str,
    cwd: Path,
    home: Path,
) -> list[tuple[str, Path, str]]:
    """Write `mcp_url` (under the given label/section name) to every detected agent."""
    results: list[tuple[str, Path, str]] = []
    section_key = f"elliot-{label}" if label != "plugin" else "elliot"

    claude_config = cwd / ".mcp.json"
    changed = _write_json_merge(
        claude_config, "mcpServers", section_key, {"type": "http", "url": mcp_url}
    )
    results.append(("Claude Code", claude_config, "updated" if changed else "already configured"))

    if shutil.which("code") or (cwd / ".vscode").exists():
        vscode_config = cwd / ".vscode" / "mcp.json"
        changed = _write_json_merge(
            vscode_config, "servers", section_key, {"type": "http", "url": mcp_url}
        )
        results.append(
            ("VS Code / Copilot", vscode_config, "updated" if changed else "already configured")
        )

    if shutil.which("cursor") or (home / ".cursor").exists() or (cwd / ".cursor").exists():
        cursor_config = cwd / ".cursor" / "mcp.json"
        changed = _write_json_merge(
            cursor_config, "mcpServers", section_key, {"type": "http", "url": mcp_url}
        )
        results.append(("Cursor", cursor_config, "updated" if changed else "already configured"))

    windsurf_dir = home / ".codeium" / "windsurf"
    if windsurf_dir.exists():
        windsurf_config = windsurf_dir / "mcp_config.json"
        changed = _write_json_merge(
            windsurf_config, "mcpServers", section_key, {"serverUrl": mcp_url}
        )
        results.append(
            ("Windsurf", windsurf_config, "updated" if changed else "already configured")
        )

    if shutil.which("codex") or (home / ".codex").exists() or (cwd / ".codex").exists():
        codex_config = cwd / ".codex" / "config.toml"
        changed = _write_codex_toml(codex_config, mcp_url, section=section_key)
        results.append(("Codex", codex_config, "updated" if changed else "already configured"))

    return results


def _cmd_connect(args: argparse.Namespace) -> None:
    """Register Elliot MCP server with every AI coding agent found on this machine.

    By default registers the *plugin* (build connectors, port 3000). Pass
    `--runtime` to also/instead register the *runtime* (serve a built
    connector to client agents, port 3001 by default). When the runtime is
    being registered, the URL is probed with a real MCP `initialize` first
    so we never write a config that points at a dead endpoint.
    """
    cwd = Path.cwd()
    home = Path.home()
    plugin_url = os.environ.get("ELLIOT_PLUGIN_URL", "http://localhost:3000")
    runtime_url = os.environ.get("ELLIOT_RUNTIME_URL", "http://localhost:3001")

    # Trailing slash matters: strict MCP clients (Codex/rmcp) drop POST bodies
    # on 307 redirects. The runtime serves at /mcp/ without redirect.
    plugin_mcp = f"{plugin_url.rstrip('/')}/mcp/"
    runtime_mcp = f"{runtime_url.rstrip('/')}/mcp/"

    targets: list[tuple[str, str]] = []
    if getattr(args, "runtime_only", False):
        targets.append(("runtime", runtime_mcp))
    else:
        targets.append(("plugin", plugin_mcp))
        if getattr(args, "runtime", False):
            targets.append(("runtime", runtime_mcp))

    print("\nElliot MCP Connect")
    print("─" * 60)

    any_registered = False
    for label, mcp_url in targets:
        print(f"\n  {label.title()} MCP: {mcp_url}")
        if label == "runtime":
            ok, reason = _probe_mcp_initialize(mcp_url)
            if not ok:
                print(f"  ✗ Skipped — runtime not reachable: {reason}")
                print("    Tip: build + export a connector, then call elliot_start_runtime.")
                continue
            print("  ✓ Verified MCP initialize handshake")

        results = _register_for_all_agents(label, mcp_url, cwd, home)
        if not results:
            print("  No supported agents detected on this machine.")
            print("  Supported: Claude Code, VS Code/Copilot, Cursor, Windsurf, Codex")
            continue
        any_registered = True
        for agent, path, status in results:
            icon = "✓" if "configured" in status else "+"
            print(f"  {icon} {agent:<22} {status}")
            print(f"    └ {path}")

    if not any_registered:
        print()
        return

    print()
    print("  Next steps:")
    print("  1. Start Elliot:          make dev")
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
    connect_cmd = sub.add_parser(
        "connect",
        help="Register Elliot MCP server with Claude Code, Cursor, VS Code, Windsurf, and Codex",
    )
    connect_cmd.add_argument(
        "--runtime",
        action="store_true",
        help=(
            "Also register the runtime URL (the connector served to client "
            "agents on port 3001). Probed with a real MCP initialize before "
            "writing — skipped if the runtime is not reachable."
        ),
    )
    connect_cmd.add_argument(
        "--runtime-only",
        action="store_true",
        dest="runtime_only",
        help="Register only the runtime URL (skip the plugin URL).",
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
