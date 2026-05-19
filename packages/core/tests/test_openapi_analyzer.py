"""Tests for elliot_core.openapi_analyzer."""

from __future__ import annotations

import pytest

from elliot_core.openapi_analyzer import (
    ProposedConnector,
    _ensure_verb_first,
    _path_to_id,
    _slugify,
    _to_snake,
    analyze_spec,
)

PETSTORE_MINIMAL = {
    "openapi": "3.0.0",
    "info": {"title": "Pet Store", "version": "1.0.0"},
    "servers": [{"url": "https://petstore.example.com"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "schema": {"type": "integer"},
                        "required": False,
                        "description": "Max items to return",
                    }
                ],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "properties": {
                                            "id": {},
                                            "name": {},
                                            "status": {},
                                        }
                                    },
                                }
                            }
                        }
                    }
                },
            }
        },
        "/pets/{id}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a single pet",
                "responses": {"200": {}},
            },
            "delete": {
                "operationId": "deletePet",
                "responses": {"204": {}},
            },
        },
    },
}


def test_analyze_returns_proposed_connector() -> None:
    result = analyze_spec(PETSTORE_MINIMAL)
    assert isinstance(result, ProposedConnector)


def test_analyze_extracts_title_slug() -> None:
    result = analyze_spec(PETSTORE_MINIMAL)
    assert result.name == "Pet Store"
    assert result.slug == "pet-store"


def test_analyze_includes_write_endpoints() -> None:
    """Write endpoints become WRITE/ACTION tools, not silently skipped."""
    result = analyze_spec(PETSTORE_MINIMAL)
    delete_tool = next(t for t in result.tools if t.http_method == "DELETE")
    assert delete_tool.category == "ACTION"
    assert delete_tool.id == "delete_pet"


def test_analyze_write_endpoints_produce_warning() -> None:
    result = analyze_spec(PETSTORE_MINIMAL)
    assert any("write endpoint" in w for w in result.warnings)


def test_analyze_extracts_parameters() -> None:
    result = analyze_spec(PETSTORE_MINIMAL)
    list_tool = next(t for t in result.tools if t.id == "list_pets")
    assert len(list_tool.parameters) == 1
    assert list_tool.parameters[0].name == "limit"
    assert list_tool.parameters[0].type == "integer"


def test_analyze_extracts_response_fields() -> None:
    result = analyze_spec(PETSTORE_MINIMAL)
    list_tool = next(t for t in result.tools if t.id == "list_pets")
    assert set(list_tool.response_fields) == {"id", "name", "status"}


def test_analyze_detects_source_url() -> None:
    result = analyze_spec(PETSTORE_MINIMAL)
    assert result.sources[0].base_url == "https://petstore.example.com"


def test_analyze_missing_openapi_key_raises() -> None:
    with pytest.raises(ValueError, match="OpenAPI 3.x"):
        analyze_spec({"info": {"title": "No version"}})


def test_warn_too_many_tools() -> None:
    paths = {
        f"/item{i}": {"get": {"operationId": f"getItem{i}", "responses": {"200": {}}}}
        for i in range(25)
    }
    spec = {**PETSTORE_MINIMAL, "paths": paths}
    result = analyze_spec(spec)
    assert any("25 tools" in w for w in result.warnings)


def test_slugify() -> None:
    assert _slugify("Pet Store API") == "pet-store-api"
    assert _slugify("My-API v2") == "my-api-v2"


def test_to_snake() -> None:
    assert _to_snake("listPets") == "list_pets"
    assert _to_snake("getPetById") == "get_pet_by_id"


def test_path_to_id_list() -> None:
    assert _path_to_id("/pets", "get") == "list_pets"


def test_path_to_id_get() -> None:
    assert _path_to_id("/pets/{id}", "get") == "get_pets"


def test_ensure_verb_first_already_verb() -> None:
    assert _ensure_verb_first("List all pets") == "List all pets"


def test_ensure_verb_first_adds_return() -> None:
    assert _ensure_verb_first("All pets in the store") == "Return all pets in the store"


_SPEC_WITH_REFS = {
    "openapi": "3.1.0",
    "info": {"title": "Ref API", "version": "2.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "components": {
        "parameters": {
            "PageParam": {
                "name": "page",
                "in": "query",
                "schema": {"type": "integer"},
                "required": False,
                "description": "Page number",
            }
        },
        "schemas": {
            "NewWidget": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "tags": {"type": ["array", "null"]},
                },
            }
        },
    },
    "paths": {
        "/widgets": {
            "parameters": [{"$ref": "#/components/parameters/PageParam"}],
            "post": {
                "operationId": "createWidget",
                "summary": "Create a widget",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/NewWidget"}}
                    }
                },
                "responses": {"201": {}},
            },
        }
    },
}


def test_analyze_resolves_param_and_body_refs() -> None:
    result = analyze_spec(_SPEC_WITH_REFS)
    tool = next(t for t in result.tools if t.http_method == "POST")
    assert tool.category == "WRITE"
    names = {p.name for p in tool.parameters}
    # path-level $ref parameter + requestBody schema $ref properties
    assert names == {"page", "name", "tags"}
    name_param = next(p for p in tool.parameters if p.name == "name")
    assert name_param.required is True
    # OpenAPI 3.1 list-valued type collapses to the non-null member.
    tags_param = next(p for p in tool.parameters if p.name == "tags")
    assert tags_param.type == "array"
