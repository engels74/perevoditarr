"""Domain error hierarchy mapped to typed problem responses (P1-T1)."""

from typing import ClassVar

import msgspec
from litestar import MediaType, Request, Response
from litestar.datastructures import State


class Problem(msgspec.Struct, kw_only=True, rename="camel"):
    status: int
    code: str
    title: str
    detail: str | None = None


class PerevoditarrError(Exception):
    status_code: ClassVar[int] = 500
    code: ClassVar[str] = "internal-error"
    title: ClassVar[str] = "Internal error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail: str | None = detail


class NotFoundError(PerevoditarrError):
    status_code: ClassVar[int] = 404
    code: ClassVar[str] = "not-found"
    title: ClassVar[str] = "Resource not found"


class ConflictError(PerevoditarrError):
    status_code: ClassVar[int] = 409
    code: ClassVar[str] = "conflict"
    title: ClassVar[str] = "Conflicting state"


class DomainValidationError(PerevoditarrError):
    status_code: ClassVar[int] = 422
    code: ClassVar[str] = "validation-failed"
    title: ClassVar[str] = "Validation failed"


class UpstreamError(PerevoditarrError):
    """Bazarr/Lingarr (or another integration) misbehaved or is unreachable."""

    status_code: ClassVar[int] = 502
    code: ClassVar[str] = "upstream-error"
    title: ClassVar[str] = "Upstream error"


class UpstreamUnavailableError(UpstreamError):
    code: ClassVar[str] = "upstream-unavailable"
    title: ClassVar[str] = "Upstream unreachable"


class UnsupportedVersionError(PerevoditarrError):
    """Instance registration rejected: upstream version below the pinned minimum (FR-I1)."""

    status_code: ClassVar[int] = 422
    code: ClassVar[str] = "unsupported-version"
    title: ClassVar[str] = "Unsupported upstream version"


def to_problem(exc: PerevoditarrError) -> Problem:
    return Problem(
        status=exc.status_code,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
    )


def domain_exception_handler(
    _: Request[object, object, State], exc: PerevoditarrError
) -> Response[Problem]:
    return Response(
        to_problem(exc), status_code=exc.status_code, media_type=MediaType.JSON
    )
