"""Tests for elliot_core.openapi_analyzer."""

from __future__ import annotations

import pytest

from elliot_core.naming import is_valid_identifier
from elliot_core.openapi_analyzer import (
    ProposedConnector,
    _compose_description,
    _path_to_id,
    _slugify,
    _to_snake,
    analyze_spec,
    parse_spec_text,
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


# ── names & descriptions are born lint-clean ──────────────────────────────────


def test_tool_names_are_snake_case_identifiers() -> None:
    """Names must be identifiers, not sentence-case titles with periods."""
    result = analyze_spec(PETSTORE_MINIMAL)
    for tool in result.tools:
        assert is_valid_identifier(tool.name), tool.name
        assert tool.name == tool.id


def test_compose_description_keeps_verb_first_summary() -> None:
    out = _compose_description("Add a new pet to the store.", "", "post", "/pet")
    assert out == "Add a new pet to the store."


def test_compose_description_never_bolts_return_onto_prose() -> None:
    # The old behaviour produced "Return add a new pet to the store."
    out = _compose_description(
        "Add a new pet to the store.", "Add a new pet to the store.", "post", "/pet"
    )
    assert out == "Add a new pet to the store."
    assert not out.lower().startswith("return add")


def test_compose_description_synthesizes_verb_from_method() -> None:
    out = _compose_description("", "This can only be done by the logged in user.", "post", "/user")
    assert out.startswith("Create a user.")
    assert "logged in user" in out


def test_compose_description_dedupes_prefix_detail() -> None:
    out = _compose_description(
        "Update an existing pet.", "Update an existing pet by Id.", "put", "/pet"
    )
    assert out == "Update an existing pet by Id."


def test_duplicate_operation_ids_get_unique_tool_ids() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Dup API", "version": "1"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/a": {"get": {"operationId": "doThing", "responses": {"200": {}}}},
            "/b": {"post": {"operationId": "doThing", "responses": {"200": {}}}},
        },
    }
    result = analyze_spec(spec)
    ids = [t.id for t in result.tools]
    assert len(ids) == len(set(ids))


# ── base URL resolution ───────────────────────────────────────────────────────


def test_relative_server_resolved_against_spec_url() -> None:
    """A relative servers[0].url must resolve against the spec's own URL —
    previously it shipped verbatim and every request 404'd."""
    spec = {**PETSTORE_MINIMAL, "servers": [{"url": "/api/v3"}]}
    result = analyze_spec(spec, spec_url="https://petstore3.swagger.io/api/v3/openapi.json")
    assert result.sources[0].base_url == "https://petstore3.swagger.io/api/v3"


def test_relative_server_without_spec_url_warns() -> None:
    spec = {**PETSTORE_MINIMAL, "servers": [{"url": "/api/v3"}]}
    result = analyze_spec(spec)
    assert result.sources[0].base_url == "/api/v3"
    assert any("relative" in w for w in result.warnings)


def test_no_servers_uses_spec_url_origin() -> None:
    spec = {k: v for k, v in PETSTORE_MINIMAL.items() if k != "servers"}
    result = analyze_spec(spec, spec_url="https://api.example.com/specs/openapi.json")
    assert result.sources[0].base_url == "https://api.example.com"


def test_no_servers_no_spec_url_warns() -> None:
    spec = {k: v for k, v in PETSTORE_MINIMAL.items() if k != "servers"}
    result = analyze_spec(spec)
    assert result.sources[0].base_url == ""
    assert any("no servers" in w for w in result.warnings)


def test_server_variables_substituted_with_defaults() -> None:
    spec = {
        **PETSTORE_MINIMAL,
        "servers": [
            {
                "url": "https://{region}.api.example.com/v1",
                "variables": {"region": {"default": "eu"}},
            }
        ],
    }
    result = analyze_spec(spec)
    assert result.sources[0].base_url == "https://eu.api.example.com/v1"


# ── parameter hygiene ─────────────────────────────────────────────────────────


def test_body_field_colliding_with_path_param_is_renamed() -> None:
    """PUT /user/{username} whose body also carries `username` must not
    propose two parameters with one name — previously an unbuildable tool."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "User API", "version": "1"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/user/{username}": {
                "put": {
                    "operationId": "updateUser",
                    "summary": "Update user resource.",
                    "parameters": [
                        {
                            "name": "username",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "username": {"type": "string"},
                                        "email": {"type": "string"},
                                    },
                                }
                            }
                        }
                    },
                    "responses": {"200": {}},
                }
            }
        },
    }
    result = analyze_spec(spec)
    tool = result.tools[0]
    names = [p.name for p in tool.parameters]
    assert len(names) == len(set(names))
    assert "username" in names
    assert "body_username" in names
    assert any("collide" in w for w in result.warnings)


def test_array_request_body_becomes_items_param() -> None:
    """A top-level array body (bulk create) was previously dropped silently."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Bulk API", "version": "1"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/users/bulk": {
                "post": {
                    "operationId": "createUsersWithList",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "username": {"type": "string"},
                                            "email": {"type": "string"},
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {"200": {}},
                }
            }
        },
    }
    result = analyze_spec(spec)
    tool = result.tools[0]
    assert len(tool.parameters) == 1
    param = tool.parameters[0]
    assert param.name == "items"
    assert param.type == "array"
    assert param.required is True
    assert "username" in param.description


def test_freeform_object_body_becomes_body_param() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Blob API", "version": "1"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/settings": {
                "post": {
                    "operationId": "putSettings",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"type": "object", "additionalProperties": True}
                            }
                        }
                    },
                    "responses": {"200": {}},
                }
            }
        },
    }
    tool = analyze_spec(spec).tools[0]
    assert [p.name for p in tool.parameters] == ["body"]
    assert tool.parameters[0].type == "object"


def test_header_params_skipped_with_warning() -> None:
    """Auth material (api_key header params) must not become agent-facing
    parameters — the source's auth block owns it."""
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Hdr API", "version": "1"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/pets/{petId}": {
                "delete": {
                    "operationId": "deletePet",
                    "parameters": [
                        {"name": "api_key", "in": "header", "schema": {"type": "string"}},
                        {
                            "name": "petId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        },
                    ],
                    "responses": {"200": {}},
                }
            }
        },
    }
    result = analyze_spec(spec)
    tool = result.tools[0]
    assert [p.name for p in tool.parameters] == ["petId"]
    assert any("api_key" in w and "header" in w for w in result.warnings)


def test_binary_body_warns_instead_of_silence() -> None:
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Upload API", "version": "1"},
        "servers": [{"url": "https://api.example.com"}],
        "paths": {
            "/pets/{petId}/image": {
                "post": {
                    "operationId": "uploadImage",
                    "parameters": [
                        {
                            "name": "petId",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "requestBody": {
                        "content": {
                            "application/octet-stream": {
                                "schema": {"type": "string", "format": "binary"}
                            }
                        }
                    },
                    "responses": {"200": {}},
                }
            }
        },
    }
    result = analyze_spec(spec)
    assert any("octet-stream" in w for w in result.warnings)


# ── auth wiring ───────────────────────────────────────────────────────────────


def test_api_key_scheme_becomes_auth_block() -> None:
    spec = {
        **PETSTORE_MINIMAL,
        "components": {
            "securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Acme-Key"}}
        },
    }
    src = analyze_spec(spec).sources[0]
    assert src.auth_hint == "api_key"
    assert src.auth is not None
    assert src.auth["type"] == "api_key"
    assert src.auth["header_name"] == "X-Acme-Key"
    assert src.auth["secret_key"] == "{{ env:PET_STORE_API_KEY }}"


def test_oauth2_scheme_becomes_per_user_auth_block() -> None:
    spec = {
        **PETSTORE_MINIMAL,
        "components": {
            "securitySchemes": {
                "oauth": {
                    "type": "oauth2",
                    "flows": {
                        "authorizationCode": {
                            "authorizationUrl": "https://auth.example.com/authorize",
                            "tokenUrl": "https://auth.example.com/token",
                            "scopes": {"read:pets": "read"},
                        }
                    },
                }
            }
        },
    }
    src = analyze_spec(spec).sources[0]
    assert src.auth_hint == "oauth2"
    assert src.auth is not None
    assert src.auth["scope"] == "per_user"
    assert src.auth["oauth2"]["authorization_url"] == "https://auth.example.com/authorize"
    assert src.auth["oauth2"]["client_id_secret"] == "{{ env:PET_STORE_CLIENT_ID }}"


def test_security_requirement_picks_preferred_scheme() -> None:
    spec = {
        **PETSTORE_MINIMAL,
        "security": [{"bearer_auth": []}],
        "components": {
            "securitySchemes": {
                "key": {"type": "apiKey", "in": "query", "name": "api_key"},
                "bearer_auth": {"type": "http", "scheme": "bearer"},
            }
        },
    }
    src = analyze_spec(spec).sources[0]
    assert src.auth_hint == "bearer"


# ── Swagger 2.0 conversion ────────────────────────────────────────────────────

_SWAGGER2 = {
    "swagger": "2.0",
    "info": {"title": "Legacy API", "version": "1.0"},
    "host": "legacy.example.com",
    "basePath": "/v2",
    "schemes": ["https"],
    "securityDefinitions": {"key": {"type": "apiKey", "in": "header", "name": "X-Key"}},
    "definitions": {
        "Widget": {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "size": {"type": "integer"}},
        }
    },
    "paths": {
        "/widgets": {
            "get": {
                "operationId": "listWidgets",
                "summary": "List widgets",
                "parameters": [
                    {"name": "limit", "in": "query", "type": "integer", "required": False}
                ],
                "responses": {
                    "200": {
                        "description": "ok",
                        "schema": {"type": "array", "items": {"$ref": "#/definitions/Widget"}},
                    }
                },
            },
            "post": {
                "operationId": "createWidget",
                "summary": "Create a widget",
                "parameters": [
                    {
                        "name": "body",
                        "in": "body",
                        "required": True,
                        "schema": {"$ref": "#/definitions/Widget"},
                    }
                ],
                "responses": {"201": {"description": "created"}},
            },
        }
    },
}


def test_swagger2_is_converted_not_rejected() -> None:
    result = analyze_spec(_SWAGGER2)
    assert any("Swagger 2.0" in w for w in result.warnings)
    assert result.sources[0].base_url == "https://legacy.example.com/v2"
    assert result.sources[0].auth_hint == "api_key"


def test_swagger2_body_and_refs_become_parameters() -> None:
    result = analyze_spec(_SWAGGER2)
    create = next(t for t in result.tools if t.id == "create_widget")
    names = {p.name for p in create.parameters}
    assert names == {"name", "size"}
    name_param = next(p for p in create.parameters if p.name == "name")
    assert name_param.required is True
    listing = next(t for t in result.tools if t.id == "list_widgets")
    assert {p.name for p in listing.parameters} == {"limit"}
    assert set(listing.response_fields) == {"name", "size"}


# ── pasted YAML ───────────────────────────────────────────────────────────────


def test_parse_spec_text_yaml() -> None:
    yaml_text = """
openapi: 3.0.0
info:
  title: Yaml API
  version: "1.0"
servers:
  - url: https://yaml.example.com
paths:
  /things:
    get:
      operationId: listThings
      summary: List things
      responses:
        "200": {}
"""
    spec = parse_spec_text(yaml_text)
    result = analyze_spec(spec)
    assert result.slug == "yaml-api"
    assert result.tools[0].id == "list_things"


def test_parse_spec_text_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="object"):
        parse_spec_text("- just\n- a\n- list\n")


# ── $ref resolution (behaviour preserved from the previous analyzer) ──────────

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
