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


def test_non_select_keyword_rejected():
    ok, reason = validate_tool_sql("SHOW TABLES")  # no forbidden keywords, but not SELECT
    assert ok is False
    assert "SELECT" in reason


# ── Regression tests for audit C3 (validate_tool_sql bypass via block comment) ──


def test_block_comment_with_semicolon_rejected():
    """A block comment hiding a semicolon must NOT bypass the multi-statement check."""
    ok, _reason = validate_tool_sql("SELECT/*; DROP TABLE x; --*/ 1")
    # The block-comment content is stripped before the semicolon check, so
    # this SQL itself is fine. But if the comment hides a real semicolon
    # outside its delimiter we MUST reject:
    sql = "SELECT 1 /* hide */; DROP TABLE x"
    ok, reason = validate_tool_sql(sql)
    assert ok is False
    assert "Multiple" in reason


def test_block_comment_only_is_empty():
    ok, reason = validate_tool_sql("/* just a comment */")
    assert ok is False
    assert "empty" in reason


def test_with_cte_accepted():
    """CTE queries (WITH ... SELECT) are permitted — they are pure read."""
    ok, _ = validate_tool_sql(
        "WITH active AS (SELECT * FROM users WHERE flag = 1) SELECT * FROM active"
    )
    assert ok is True


def test_with_cte_then_insert_rejected():
    """A CTE that wraps an INSERT must be rejected."""
    ok, reason = validate_tool_sql("WITH x AS (SELECT 1) INSERT INTO users (id) VALUES (1)")
    assert ok is False
    assert "Forbidden" in reason


def test_attach_rejected():
    ok, reason = validate_tool_sql("ATTACH DATABASE '/etc/passwd' AS pwd")
    assert ok is False
    assert "Forbidden" in reason


def test_vacuum_rejected():
    ok, reason = validate_tool_sql("VACUUM")
    assert ok is False
    assert "Forbidden" in reason


def test_trailing_semicolon_allowed():
    """A single trailing semicolon is benign — only embedded ones are multi-statement."""
    ok, _ = validate_tool_sql("SELECT 1;")
    assert ok is True
