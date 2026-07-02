"""Typed accessors for decoding untyped JSON test-response bodies.

`httpx.Response.json()` is declared to return `Any`, which trips
basedpyright's `reportAny` at every call site. These helpers concentrate
that single untyped boundary in one place and hand back concrete
`dict[str, object]` / `list[object]` containers, so test bodies can narrow
with plain indexing without leaking `Any`. The runtime `isinstance` guards
keep the `cast` sound: a decoded JSON object always has `str` keys, and
`object` values are maximally permissive.
"""

import json
from pathlib import Path
from typing import cast

import httpx


def json_obj(response: httpx.Response) -> dict[str, object]:
    """Decode a response body expected to be a JSON object."""
    body: object = response.json()  # pyright: ignore[reportAny]  # httpx .json() -> Any boundary
    assert isinstance(body, dict), f"expected JSON object, got {type(body).__name__}"
    return cast("dict[str, object]", body)


def json_list(response: httpx.Response) -> list[object]:
    """Decode a response body expected to be a JSON array."""
    body: object = response.json()  # pyright: ignore[reportAny]  # httpx .json() -> Any boundary
    assert isinstance(body, list), f"expected JSON array, got {type(body).__name__}"
    return cast("list[object]", body)


def as_obj(value: object) -> dict[str, object]:
    """Narrow a nested JSON value to an object."""
    assert isinstance(value, dict), f"expected JSON object, got {type(value).__name__}"
    return cast("dict[str, object]", value)


def as_list(value: object) -> list[object]:
    """Narrow a nested JSON value to an array."""
    assert isinstance(value, list), f"expected JSON array, got {type(value).__name__}"
    return cast("list[object]", value)


def load_json_obj(path: Path) -> dict[str, object]:
    """Load a JSON fixture file whose top level is an object."""
    body: object = json.loads(path.read_text())  # pyright: ignore[reportAny]  # json.loads -> Any boundary
    assert isinstance(body, dict), f"expected JSON object, got {type(body).__name__}"
    return cast("dict[str, object]", body)
