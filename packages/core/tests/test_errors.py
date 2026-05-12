"""Tests for ElliotError hierarchy and MCP helpers."""

from elliot_core.errors import (
    AuthError,
    ElliotError,
    NotFoundError,
    RateLimitError,
    SourceFetchError,
    ValidationError,
    is_elliot_error,
    to_mcp_error_content,
)


def test_elliot_error_attrs():
    err = ElliotError("TOOL_NOT_FOUND", "No tool named x")
    assert err.code == "TOOL_NOT_FOUND"
    assert err.message == "No tool named x"
    assert err.detail is None
    assert str(err) == "No tool named x"


def test_typed_subclasses():
    assert ValidationError("bad").code == "VALIDATION_ERROR"
    assert NotFoundError("missing").code == "NOT_FOUND"
    assert AuthError("denied").code == "AUTH_FAILED"
    assert SourceFetchError("upstream down").code == "UPSTREAM_FETCH_FAILED"
    assert RateLimitError("slow down").code == "RATE_LIMIT_EXCEEDED"


def test_is_elliot_error():
    assert is_elliot_error(ElliotError("X", "msg"))
    assert is_elliot_error(ValidationError("v"))
    assert not is_elliot_error(ValueError("v"))
    assert not is_elliot_error("not an error")


def test_to_mcp_error_content_elliot():
    err = ElliotError("TOOL_NOT_FOUND", "No tool named x")
    content = to_mcp_error_content(err)
    assert content["type"] == "text"
    assert "TOOL_NOT_FOUND" in content["text"]
    assert "No tool named x" in content["text"]


def test_to_mcp_error_content_generic():
    err = RuntimeError("unexpected")
    content = to_mcp_error_content(err)
    assert content["type"] == "text"
    assert "Unexpected error" in content["text"]


def test_elliot_error_with_detail():
    err = ElliotError("VALIDATION_ERROR", "bad param", detail={"field": "name"})
    assert err.detail == {"field": "name"}


def test_elliot_error_repr():
    err = ElliotError("NOT_FOUND", "thing missing")
    assert repr(err) == "ElliotError(code='NOT_FOUND', message='thing missing')"
