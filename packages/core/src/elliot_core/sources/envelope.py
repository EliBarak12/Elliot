"""Locate the array of records inside a JSON response envelope.

A SINGLE, shared implementation used by both the design-time REST fetcher
(``api_fetcher``) and the runtime executor (``connector-runtime``). Previously
each had its own copy of this logic and the two drifted: the runtime copy only
inspected the top level, so a connector built over an API that nests its rows
one layer down — CKAN's ``{"result": {"results": [...]}}``, JSON-RPC's
``{"result": {...}}``, ``{"data": {"items": [...]}}`` — materialized the wrapper
object as a single row and every tool returned nothing. Centralizing the logic
here means the two paths can never diverge again, and teaching it to descend
through wrapper objects fixes the whole class of nested-envelope APIs without
the connector builder having to hand-set ``data_path``.
"""

from __future__ import annotations

from typing import Any

# Conventional wrapper keys, in deterministic priority order. When an envelope
# exposes several arrays, the one under a standard key wins over auto-detection.
_RECORD_KEYS = ("data", "items", "results", "records", "rows")

# Bound the descent: record arrays live within the first couple of envelope
# layers, and a ceiling keeps a pathological/deeply-nested payload cheap.
_MAX_DEPTH = 4


def _is_object_array(value: Any) -> bool:
    """True if ``value`` is a list that is empty or whose first item is a dict.

    A list of scalars (e.g. an ``ids`` or ``tags`` array) is never a row set, so
    it is deliberately excluded. An *empty* list counts: an API that legitimately
    returned zero records must yield 0 rows, not fall through to wrapping the
    envelope.
    """
    return isinstance(value, list) and (not value or isinstance(value[0], dict))


def _find_record_array(data: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Breadth-first search an envelope for THE array of record objects.

    Descends through nested wrapper objects one level at a time. At the
    shallowest depth that exposes any object-array:

      * a value under a standard record key (``data``/``items``/...) wins, else
      * if exactly one object-array is present it is taken, else
      * more than one is ambiguous — return ``None`` and let the caller wrap the
        envelope rather than guess wrong.

    Returns ``None`` when no object-array is found within ``_MAX_DEPTH`` layers.
    """
    frontier: list[dict[str, Any]] = [data]
    depth = 0
    while frontier and depth < _MAX_DEPTH:
        # A standard record key at this level takes priority, nearest first.
        for node in frontier:
            for key in _RECORD_KEYS:
                if _is_object_array(node.get(key)):
                    return node[key]
        # Otherwise collect every object-array exposed at this level and queue
        # nested dicts for the next, deeper pass.
        found: list[list[dict[str, Any]]] = []
        deeper: list[dict[str, Any]] = []
        for node in frontier:
            for value in node.values():
                if _is_object_array(value):
                    found.append(value)
                elif isinstance(value, dict):
                    deeper.append(value)
        if found:
            return found[0] if len(found) == 1 else None
        frontier = deeper
        depth += 1
    return None


def extract_rows(data: Any, data_path: str | None = None) -> list[dict[str, Any]]:
    """Return the list of record dicts inside an arbitrary JSON payload.

    ``data_path`` (a JMESPath) is applied first when provided; the located value
    is then unwrapped with the same envelope logic, so a path that points at a
    wrapper object (e.g. ``"result"``) still yields its inner records array.
    """
    if data_path:
        import jmespath

        data = jmespath.search(data_path, data)
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    found = _find_record_array(data)
    if found is not None:
        return found
    # No array we could confidently identify — treat the object as a single row.
    return [data]


def _has_object_array(data: Any, depth: int = 0) -> bool:
    """True if ``data`` hides an object-array anywhere within ``_MAX_DEPTH``."""
    if depth >= _MAX_DEPTH or not isinstance(data, dict):
        return False
    for value in data.values():
        if _is_object_array(value):
            return True
        if isinstance(value, dict) and _has_object_array(value, depth + 1):
            return True
    return False


def looks_like_unextracted_envelope(rows: list[dict[str, Any]]) -> bool:
    """True when extraction collapsed an envelope to a single wrapper row.

    Signal for a build-time warning: the payload yielded exactly one row that
    still hides a record array somewhere inside it — almost always a sign the
    records array couldn't be auto-located (e.g. several candidate arrays) and
    the source needs an explicit ``data_path``.
    """
    return len(rows) == 1 and _has_object_array(rows[0])
