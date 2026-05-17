import pytest

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


# ── Dangerous file/network/exec constructs inside a SELECT ────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "COPY users TO '/tmp/x'",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_read_binary_file('/etc/passwd')",
        "SELECT pg_ls_dir('/')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT lo_export(1, '/tmp/x')",
        "SELECT dblink('host=evil', 'SELECT 1')",
        "SELECT pg_sleep(10)",
        "SELECT load_extension('evil.so')",
        "SELECT readfile('/etc/passwd')",
        "SELECT writefile('/tmp/x', 'data')",
        "SELECT LOAD_FILE('/etc/passwd')",
        "SELECT * FROM users INTO OUTFILE '/tmp/x'",
        "SELECT * FROM users INTO DUMPFILE '/tmp/x'",
        "SELECT sys_exec('rm -rf /')",
        "EXEC xp_cmdshell 'dir'",
    ],
)
def test_dangerous_constructs_rejected(sql: str) -> None:
    """File/network/exec functions and write redirections are blocked even
    when the statement otherwise looks like a SELECT."""
    ok, reason = validate_tool_sql(sql)
    assert ok is False
    assert "Forbidden" in reason


def test_dangerous_construct_case_insensitive() -> None:
    ok, reason = validate_tool_sql("select PG_SLEEP(5)")
    assert ok is False
    assert "Forbidden" in reason


def test_dangerous_substring_not_falsely_flagged() -> None:
    """A column merely named like a dangerous token but not the construct
    itself (word-boundary) must still match — but a longer word should not."""
    # 'pg_sleeper' is a different identifier; word boundary prevents a match.
    ok, _ = validate_tool_sql("SELECT pg_sleeper FROM t")
    assert ok is True
