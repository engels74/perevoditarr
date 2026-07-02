"""Repo-wide persistence guards (Conventions §0).

Every relationship must declare an explicit, async-safe loading strategy —
lazy="raise" is the default guard, selectin/joined for deliberate eager
loads. A bare lazy="select" would MissingGreenlet under async at runtime.
"""

from advanced_alchemy.base import orm_registry
from sqlalchemy.orm import configure_mappers

from perevoditarr import models as models  # register all mappers (re-export)
from perevoditarr.core.db import metadata

_ALLOWED_LAZY = {"raise", "raise_on_sql", "selectin", "joined", "noload", "write_only"}


def test_every_relationship_declares_async_safe_loading() -> None:
    configure_mappers()
    offenders: list[str] = []
    for mapper in orm_registry.mappers:
        for rel in mapper.relationships:
            if rel.lazy not in _ALLOWED_LAZY:
                offenders.append(
                    f"{mapper.class_.__name__}.{rel.key} (lazy={rel.lazy!r})"
                )
    assert not offenders, f"relationships without async-safe loading: {offenders}"


def test_naming_conventions_applied() -> None:
    convention = metadata.naming_convention
    assert convention.get("pk") is not None
    assert convention.get("fk") is not None
    assert convention.get("uq") is not None
