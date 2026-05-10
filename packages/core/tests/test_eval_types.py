"""Tests for eval_types: EvalSuite, EvalCase, load_eval_suite."""

from __future__ import annotations

from pathlib import Path

from elliot_core.eval_types import EvalExpect, EvalSuite, load_eval_suite


def test_load_eval_suite(tmp_path: Path) -> None:
    yaml_content = """\
name: Test Suite
connector: test
cases:
  - id: case1
    tool_id: list_animals
    arguments: {}
    expect:
      min_rows: 1
"""
    p = tmp_path / "test.eval.yaml"
    p.write_text(yaml_content)
    suite = load_eval_suite(p)
    assert suite.connector == "test"
    assert suite.name == "Test Suite"
    assert len(suite.cases) == 1
    assert suite.cases[0].expect.min_rows == 1


def test_suite_defaults() -> None:
    suite = EvalSuite(name="S", connector="c", cases=[])
    assert suite.version == "1.0.0"
    assert suite.cases == []


def test_expect_defaults() -> None:
    e = EvalExpect()
    assert e.no_error is True
    assert e.min_rows == 0
    assert e.max_rows is None
    assert e.fields_present == []
    assert e.all_rows_match is None
    assert e.error_code is None
    assert e.max_token_estimate is None


def test_load_eval_suite_with_all_fields(tmp_path: Path) -> None:
    yaml_content = """\
name: Full Suite
connector: pets
version: "2.0.0"
cases:
  - id: case1
    description: "Must return dogs"
    tool_id: list_animals
    arguments:
      species: dog
    expect:
      no_error: true
      min_rows: 0
      all_rows_match:
        field: species
        value: dog
      max_token_estimate: 500
"""
    p = tmp_path / "full.eval.yaml"
    p.write_text(yaml_content)
    suite = load_eval_suite(p)
    assert suite.version == "2.0.0"
    case = suite.cases[0]
    assert case.arguments == {"species": "dog"}
    assert case.expect.all_rows_match is not None
    assert case.expect.all_rows_match.field == "species"
    assert case.expect.max_token_estimate == 500
