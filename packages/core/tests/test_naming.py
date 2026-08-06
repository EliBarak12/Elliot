"""Naming helpers."""


def test_humanize_identifier_makes_a_title_not_an_identifier() -> None:
    """MCP's `title` is the label a person reads, distinct from `name`.

    The runtime served `td.name` as the title, and the linter pushes tool ids
    and names toward snake_case, so a normally-authored connector published
    title="list_orders" — an identifier presented as a title, which Elliot's
    own directory-readiness check ("Every tool has a human-readable title")
    then passed because it only tests for a non-empty string.
    """
    from elliot_core.naming import humanize_identifier

    assert humanize_identifier("list_orders") == "List orders"
    assert humanize_identifier("get_order_by_id") == "Get order by id"
    assert humanize_identifier("searchCustomers") == "Search customers"
    # An acronym splits from the word after it rather than fusing.
    assert humanize_identifier("HTTPRequest") == "Http request"
    # A single word is still capitalised, not left bare.
    assert humanize_identifier("search") == "Search"


def test_humanize_identifier_leaves_authored_titles_alone() -> None:
    """A space means the author wrote prose; restyling it is not our business."""
    from elliot_core.naming import humanize_identifier

    assert humanize_identifier("Cancel a vet visit") == "Cancel a vet visit"
    assert humanize_identifier("List Orders") == "List Orders"
    assert humanize_identifier("") == ""
    assert humanize_identifier("   ") == ""
