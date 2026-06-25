from elliot_core.sqlite.column_namer import deduplicate_names, safe_name


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


def test_preserves_unicode_letters():
    # Hebrew header must survive instead of collapsing to "col" (P1).
    assert safe_name("שם") == "שם"
    assert safe_name("מספר רישיון") == "מספר_רישיון"


def test_unicode_mixed_with_ascii():
    assert safe_name("City עיר") == "city_עיר"


def test_length_is_bounded():
    assert len(safe_name("x" * 200)) <= 63


def test_distinct_unicode_names_do_not_collide():
    # Two different Hebrew headers must produce two different safe names.
    assert safe_name("שם") != safe_name("עיר")
