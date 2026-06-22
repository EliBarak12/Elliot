"""Pydantic models and loader for .eval.yaml evaluation suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from elliot_core.eval.matchers import MatchMode


class ExpectRowsMatch(BaseModel):
    field: str
    value: Any
    # How to compare each row's field against `value`. Defaults to exact so
    # existing suites keep their behaviour; set "numeric"/"normalized" to make
    # "$11,614.72" match 11614.72, or "scientific" for exponent-form answers.
    match: MatchMode = "exact"
    abs_tol: float | None = None
    rel_tol: float | None = None
    sig_figs: int | None = None


class FieldAssertion(BaseModel):
    """Assert that one field of one result row matches an expected value.

    Unlike `all_rows_match` (which checks every row), this targets a single row
    (default: the first) — the shape an answer-style eval needs, e.g. "the
    `final_amount` field of row 0 equals 11614.72 to 2 decimal places".
    """

    field: str
    equals: Any = None
    match: MatchMode = "exact"
    abs_tol: float | None = None
    rel_tol: float | None = None
    sig_figs: int | None = None
    row: int = 0


class EvalExpect(BaseModel):
    no_error: bool = True
    min_rows: int = 0
    max_rows: int | None = None
    fields_present: list[str] = []
    all_rows_match: ExpectRowsMatch | None = None
    field_assertions: list[FieldAssertion] = []
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
