# Task 062 — Eval Test Case Format

## Goal
Define a YAML schema for connector evaluation test cases. Each case specifies: which tool to call, with what arguments, and what the result must satisfy. Cases live in a `.eval.yaml` file next to the connector file.

## Why
Manual testing in Studio Playground is slow and doesn’t catch regressions. Eval cases are the automated contract for a connector: “this tool, with these inputs, must produce this kind of output”. Run them in CI.

## Schema

### `*.eval.yaml`

```yaml
name: "Pet Store Eval Suite"
connector: "petstore"          # must match ConnectorConfig.slug
version: "1.0.0"               # semver, for tracking regressions

cases:
  - id: list_all_animals
    description: "No-filter call should return at least one animal"
    tool_id: list_animals
    arguments: {}
    expect:
      no_error: true
      min_rows: 1
      fields_present: ["id", "name", "species"]
      max_token_estimate: 500

  - id: filter_by_species_dog
    description: "Species filter should return only dogs"
    tool_id: list_animals
    arguments:
      species: dog
    expect:
      no_error: true
      min_rows: 0           # 0 is OK — there may be no dogs
      all_rows_match:
        field: species
        value: dog

  - id: get_existing_animal
    description: "Valid ID should return one row"
    tool_id: get_animal
    arguments:
      id: 1
    expect:
      no_error: true
      min_rows: 1
      max_rows: 1
      fields_present: ["id", "name"]

  - id: get_nonexistent_animal
    description: "Missing ID should return a structured NOT_FOUND error"
    tool_id: get_animal
    arguments:
      id: 999999
    expect:
      error_code: NOT_FOUND
      max_rows: 0
```

## Pydantic model (add to `elliot_core/eval_types.py`)

```python
from __future__ import annotations
from typing import Any
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
```

## Loader

```python
# elliot_core/eval_types.py  (continued)
import yaml
from pathlib import Path

def load_eval_suite(path: str | Path) -> EvalSuite:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return EvalSuite.model_validate(data)
```

## Naming convention

Eval files live next to the connector they test:

```
connectors/
  pets.connector.json
  pets.eval.yaml          ← same slug, .eval.yaml suffix
```

## Tests

```python
from elliot_core.eval_types import load_eval_suite

def test_load_eval_suite(tmp_path):
    yaml_content = """
    name: Test
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
    assert len(suite.cases) == 1
    assert suite.cases[0].expect.min_rows == 1
```
