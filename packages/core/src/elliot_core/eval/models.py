from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class EvalCase:
    id: str
    tool_id: str
    params: dict[str, Any]
    expected_rows: list[dict[str, Any]] | None = None
    match_mode: Literal["exact", "contains", "shape"] = "contains"
    description: str = ""


@dataclass
class EvalSuite:
    id: str
    name: str
    cases: list[EvalCase] = field(default_factory=list)


@dataclass
class EvalCaseResult:
    case_id: str
    tool_id: str
    passed: bool
    actual_rows: list[dict[str, Any]]
    latency_ms: float
    error: str | None = None


@dataclass
class EvalRunResult:
    suite_id: str
    run_at: str
    score: float
    passed: int
    failed: int
    cases: list[EvalCaseResult] = field(default_factory=list)
