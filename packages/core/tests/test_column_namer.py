from elliot_core.sqlite.column_namer import (
    MAX_IDENTIFIER_LENGTH,
    bound_name,
    deduplicate_names,
    safe_name,
)


def test_reserved_word():
    assert safe_name("from") == "from_col"


def test_hyphen_becomes_underscore():
    assert safe_name("user-id") == "user_id"


def test_leading_digit():
    assert safe_name("1abc") == "col_1abc"


def test_empty_string():
    assert safe_name("") == "col"


def test_spaces():
    assert safe_name("First Name") == "first_name"


def test_uppercase_reserved():
    assert safe_name("SELECT") == "select_col"


def test_multiple_separators():
    assert safe_name("a--b__c") == "a_b_c"


def test_deduplicate_no_dups():
    assert deduplicate_names(["a", "b", "c"]) == ["a", "b", "c"]


def test_deduplicate_with_dups():
    assert deduplicate_names(["a", "b", "a"]) == ["a", "b", "a_2"]


def test_deduplicate_triple():
    result = deduplicate_names(["x", "x", "x"])
    assert result == ["x", "x_2", "x_3"]


def test_bound_name_short_unchanged():
    assert bound_name("address_geo_lat") == "address_geo_lat"
    assert bound_name("a" * MAX_IDENTIFIER_LENGTH) == "a" * MAX_IDENTIFIER_LENGTH


def test_bound_name_truncates_over_limit():
    long = "sprites_versions_generation_viii_brilliant_diamond_shining_pearl_front_default"
    bounded = bound_name(long)
    assert len(bounded) <= MAX_IDENTIFIER_LENGTH
    assert bounded.startswith("sprites_versions_generation_viii")


def test_bound_name_distinct_for_distinct_inputs():
    # Two long names sharing a 54-char prefix must not collapse to one column.
    a = "x" * 60 + "_alpha"
    b = "x" * 60 + "_beta"
    assert bound_name(a) != bound_name(b)
    assert len(bound_name(a)) <= MAX_IDENTIFIER_LENGTH
    assert len(bound_name(b)) <= MAX_IDENTIFIER_LENGTH


def test_bound_name_deterministic():
    long = "y" * 100
    assert bound_name(long) == bound_name(long)
