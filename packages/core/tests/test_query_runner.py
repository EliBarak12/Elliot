from elliot_core.sqlite.query_runner import validate_tool_sql


def test_valid_select():
    ok, reason = validate_tool_sql("SELECT * FROM t")
    assert ok is True
    assert reason == ""


def test_drop_rejected():
    ok, reason = validate_tool_sql("DROP TABLE t")
    assert ok is False
    assert "Forbidden" in reason


def test_semicolon_rejected():
    ok, reason = validate_tool_sql("SELECT 1; DROP TABLE t")
    assert ok is False
    assert "Multiple" in reason


def test_comment_stripped():
    ok, reason = validate_tool_sql("SELECT * FROM t -- ; DROP TABLE t")
    assert ok is True


def test_pragma_rejected():
    ok, reason = validate_tool_sql("PRAGMA table_info(t)")
    assert ok is False


def test_empty_sql():
    ok, reason = validate_tool_sql("")
    assert ok is False
    assert "empty" in reason
