"""Tests for the Postman Collection analyzer."""

from __future__ import annotations

import json

import pytest

from elliot_core.postman_analyzer import analyze_postman, is_postman_collection

_COLLECTION = {
    "info": {
        "name": "Acme API",
        "_postman_id": "abc-123",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "auth": {"type": "bearer"},
    "item": [
        {
            "name": "Customers",
            "item": [
                {
                    "name": "List Customers",
                    "request": {
                        "method": "GET",
                        "description": "List all customers",
                        "url": {
                            "raw": "https://api.acme.com/customers?plan=pro",
                            "path": ["customers"],
                            "query": [{"key": "plan", "value": "pro"}],
                        },
                    },
                    "response": [{"body": '[{"id":1,"name":"a","email":"x"}]'}],
                },
                {
                    "name": "Get Customer",
                    "request": {
                        "method": "GET",
                        "url": {
                            "raw": "https://api.acme.com/customers/:id",
                            "path": ["customers", ":id"],
                            "variable": [{"key": "id"}],
                        },
                    },
                },
            ],
        },
        {
            "name": "Create Order",
            "request": {
                "method": "POST",
                "url": "https://api.acme.com/orders",
                "body": {"mode": "raw", "raw": '{"customer_id": 1, "total": 99}'},
            },
        },
    ],
}


def test_is_postman_collection_true() -> None:
    assert is_postman_collection(_COLLECTION) is True


def test_is_postman_collection_false_for_openapi() -> None:
    assert is_postman_collection({"openapi": "3.0.0", "paths": {}}) is False


def test_analyze_postman_finds_all_requests() -> None:
    proposed = analyze_postman(_COLLECTION)
    assert proposed.name == "Acme API"
    assert proposed.slug == "acme-api"
    assert len(proposed.tools) == 3


def test_analyze_postman_detects_auth_and_base_url() -> None:
    proposed = analyze_postman(_COLLECTION)
    assert proposed.sources[0].auth_hint == "bearer"
    assert proposed.sources[0].base_url == "https://api.acme.com"


def test_analyze_postman_categorises_methods() -> None:
    proposed = analyze_postman(_COLLECTION)
    by_id = {t.id: t for t in proposed.tools}
    assert by_id["list_customers"].category == "READ"
    assert by_id["create_order"].category == "WRITE"


def test_analyze_postman_extracts_parameters() -> None:
    proposed = analyze_postman(_COLLECTION)
    by_id = {t.id: t for t in proposed.tools}
    list_params = {p.name for p in by_id["list_customers"].parameters}
    assert "plan" in list_params
    get_params = {p.name: p for p in by_id["get_customer"].parameters}
    assert get_params["id"].required is True
    order_params = {p.name for p in by_id["create_order"].parameters}
    assert {"customer_id", "total"} <= order_params


def test_analyze_postman_extracts_response_fields() -> None:
    proposed = analyze_postman(_COLLECTION)
    by_id = {t.id: t for t in proposed.tools}
    assert "email" in by_id["list_customers"].response_fields


def test_analyze_postman_accepts_json_string() -> None:
    proposed = analyze_postman(json.dumps(_COLLECTION))
    assert len(proposed.tools) == 3


def test_analyze_postman_rejects_non_collection() -> None:
    with pytest.raises(ValueError, match="Postman"):
        analyze_postman({"openapi": "3.0.0"})


def test_analyze_postman_warns_on_write_tools() -> None:
    proposed = analyze_postman(_COLLECTION)
    assert any("write" in w.lower() for w in proposed.warnings)
