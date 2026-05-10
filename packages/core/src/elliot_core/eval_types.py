"""Pydantic models and loader for .eval.yaml evaluation suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class ExpectRowsMatch(BaseModel):
    field: str
    value: Any


class EvalExpect(BaseModel):
    no_error: bool = True
    min_rows: int = 0
    max_rows: int | None = None
    fields_present: list[str] = []
    all_rows_match: ExpectRowsMatch | None = None
    error_code: str | None = None
    max_token_estimate: int | None = None


class EvalCase(BaseModel):
    id: str
    description: str = ""
    tool_id: str
    arguments: dict[str, Any] = {}
    expect: EvalExpect = EvalExpect()


class EvalSuite(BaseModel):
    name: str
    connector: str
    version: str = "1.0.0"
    cases: list[EvalCase]


def load_eval_suite(path: str | Path) -> EvalSuite:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return EvalSuite.model_validate(data)
