"""Shared API DTO foundations: camelCase wire policy and pagination envelope.

All /api/v1 DTOs derive from ApiStruct so the TS client sees camelCase while
Python stays snake_case (Conventions §0). Perevoditarr's own request bodies
additionally set forbid_unknown_fields=True (via ApiRequest).
"""

import msgspec


class ApiStruct(msgspec.Struct, kw_only=True, rename="camel"):
    """Base for all /api/v1 response DTOs."""


class ApiRequest(
    msgspec.Struct, kw_only=True, rename="camel", forbid_unknown_fields=True
):
    """Base for all /api/v1 request bodies: unknown fields are rejected."""


class Page[T](ApiStruct):
    """Consistent pagination envelope for every list endpoint (P1-T7)."""

    items: list[T]
    total: int
    limit: int
    offset: int
