# Task 061 — Tool Quality Linter

## Goal
Add a static analyser to `elliot-core` that reads a `ConnectorConfig` and produces a list of typed issues with severity levels. Run via CLI: `uv run elliot lint my-api.connector.json`.

## Why
Badly designed tools cause agents to fail silently. An unbounded `SELECT *` returns thousands of rows and fills the context window. A vague description causes the agent to call the wrong tool. A single-letter parameter name causes wrong argument binding. The linter makes these problems visible *before* shipping to agents.

## File to create

### `packages/core/src/elliot_core/linter.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .types import ConnectorConfig


Severity = Literal["ERROR", "WARN", "INFO"]


@dataclass
class LintIssue:
    severity: Severity
    code: str
    tool_id: str | None
    message: str
    suggestion: str


def lint_connector(config: ConnectorConfig) -> list[LintIssue]:
    issues: list[LintIssue] = []

    for tool in config.tools:
        # Description checks
        if not tool.description or len(tool.description.strip()) < 15:
            issues.append(LintIssue(
                severity="ERROR", code="DESCRIPTION_TOO_SHORT", tool_id=tool.id,
                message=f"Tool '{tool.id}' description is too short ({len(tool.description)} chars).",
                suggestion="Write at least 15 characters starting with a verb: \"Return all...\", \"Get a single...\"",
            ))
        elif not _starts_with_verb(tool.description):
            issues.append(LintIssue(
                severity="WARN", code="DESCRIPTION_MISSING_VERB", tool_id=tool.id,
                message=f"Tool '{tool.id}' description should start with a verb.",
                suggestion="Rewrite as \"Return...\", \"Get...\", \"List...\", \"Create...\", \"Count...\"",
            ))

        # SQL checks
        sql_upper = tool.sql.upper()
        if "SELECT *" in sql_upper and "LIMIT" not in sql_upper and "WHERE" not in sql_upper:
            issues.append(LintIssue(
                severity="ERROR", code="UNBOUNDED_SELECT", tool_id=tool.id,
                message=f"Tool '{tool.id}' uses SELECT * with no WHERE or LIMIT.",
                suggestion="Add LIMIT 50 or add a required/optional filter parameter.",
            ))
        elif "SELECT *" in sql_upper and "LIMIT" not in sql_upper:
            issues.append(LintIssue(
                severity="WARN", code="SELECT_STAR_NO_LIMIT", tool_id=tool.id,
                message=f"Tool '{tool.id}' uses SELECT * without a LIMIT.",
                suggestion="Add LIMIT :limit with a default, or select only the columns agents need.",
            ))

        # Parameter checks
        for param in tool.parameters:
            if len(param.name) <= 2:
                issues.append(LintIssue(
                    severity="WARN", code="PARAMETER_NAME_TOO_SHORT", tool_id=tool.id,
                    message=f"Tool '{tool.id}' has a parameter named '{param.name}' which is ambiguous.",
                    suggestion=f"Rename '{param.name}' to something descriptive like 'user_id' or 'status_filter'.",
                ))
            if not param.description or len(param.description.strip()) < 5:
                issues.append(LintIssue(
                    severity="WARN", code="PARAMETER_MISSING_DESCRIPTION", tool_id=tool.id,
                    message=f"Tool '{tool.id}' parameter '{param.name}' has no description.",
                    suggestion="Add a description so agents know what value to pass.",
                ))

        # WRITE/ACTION tools
        if tool.category in ("WRITE", "ACTION") and "write" not in tool.description.lower() \
                and "create" not in tool.description.lower() and "update" not in tool.description.lower() \
                and "delete" not in tool.description.lower() and "send" not in tool.description.lower():
            issues.append(LintIssue(
                severity="INFO", code="WRITE_TOOL_DESCRIPTION", tool_id=tool.id,
                message=f"Tool '{tool.id}' is category {tool.category} but description doesn't mention mutation.",
                suggestion="Add the mutation verb (\"Creates...\", \"Deletes...\", \"Sends...\") so agents don't call it accidentally.",
            ))

    # Source checks
    for source in config.sources:
        if source.auth and source.auth.secret_key:
            if source.auth.secret_key in (source.url or ""):
                issues.append(LintIssue(
                    severity="ERROR", code="SECRET_IN_URL", tool_id=None,
                    message=f"Source '{source.id}' may have a secret embedded in the URL.",
                    suggestion="Use auth.secret_key to reference an env var; never put secrets in URLs.",
                ))

    return issues


_VERBS = {
    "return", "get", "list", "fetch", "find", "search", "count", "create",
    "update", "delete", "send", "run", "execute", "check", "calculate", "summarise", "summarize",
}


def _starts_with_verb(description: str) -> bool:
    first_word = description.strip().split()[0].lower().rstrip(".,:")
    return first_word in _VERBS
```

## CLI command (add to `elliot-core` entry points)

```toml
# packages/core/pyproject.toml
[project.scripts]
elliot = "elliot_core.cli:main"
```

```python
# packages/core/src/elliot_core/cli.py
import sys
from pathlib import Path
from .linter import lint_connector
from .loader import load_connector   # or import from runtime

def main():
    import argparse
    parser = argparse.ArgumentParser(prog="elliot")
    sub = parser.add_subparsers(dest="command")

    lint_cmd = sub.add_parser("lint", help="Check a connector file for agent-readiness")
    lint_cmd.add_argument("path", help="Path to .connector.json")

    args = parser.parse_args()

    if args.command == "lint":
        config = load_connector(args.path)
        issues = lint_connector(config)
        errors = [i for i in issues if i.severity == "ERROR"]
        warns  = [i for i in issues if i.severity == "WARN"]
        infos  = [i for i in issues if i.severity == "INFO"]

        for issue in issues:
            icon = {"ERROR": "❌", "WARN": "⚠️ ", "INFO": "ℹ️ "}[issue.severity]
            tool = f"[{issue.tool_id}]" if issue.tool_id else "[connector]"
            print(f"{icon} {issue.severity:<5} {tool:<20} {issue.code}")
            print(f"         {issue.message}")
            print(f"         Fix: {issue.suggestion}\n")

        total = len(issues)
        print(f"{total} issue(s): {len(errors)} errors, {len(warns)} warnings, {len(infos)} info")
        sys.exit(1 if errors else 0)
```

## Tests

```python
from elliot_core.linter import lint_connector
from elliot_core.types import ConnectorConfig, ToolDefinition

def test_unbounded_select_is_error(minimal_connector):
    # Give the tool a SELECT * with no WHERE or LIMIT
    minimal_connector.tools[0].sql = "SELECT * FROM animals"
    issues = lint_connector(minimal_connector)
    codes = [i.code for i in issues]
    assert "UNBOUNDED_SELECT" in codes
    assert any(i.severity == "ERROR" for i in issues if i.code == "UNBOUNDED_SELECT")

def test_short_description_is_error(minimal_connector):
    minimal_connector.tools[0].description = "Get it"
    issues = lint_connector(minimal_connector)
    assert any(i.code == "DESCRIPTION_TOO_SHORT" for i in issues)

def test_clean_connector_has_no_issues(good_connector):
    issues = lint_connector(good_connector)
    assert not any(i.severity == "ERROR" for i in issues)
```
