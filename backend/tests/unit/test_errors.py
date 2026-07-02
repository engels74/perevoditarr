from litestar import get

# litestar's own signature for create_test_client is partially unknown.
from litestar.testing import (
    create_test_client,  # pyright: ignore[reportUnknownVariableType]
)

from perevoditarr.core.errors import (
    NotFoundError,
    PerevoditarrError,
    UnsupportedVersionError,
    domain_exception_handler,
)
from tests.support import json_obj


@get("/boom")
async def boom() -> None:
    raise UnsupportedVersionError("Bazarr 1.4.0 is below the pinned minimum 1.5.6")


@get("/missing")
async def missing() -> None:
    raise NotFoundError()


def test_domain_errors_map_to_typed_problem_responses() -> None:
    with create_test_client(
        route_handlers=[boom, missing],
        exception_handlers={PerevoditarrError: domain_exception_handler},
    ) as client:
        response = client.get("/boom")
        assert response.status_code == 422
        body = json_obj(response)
        assert body["code"] == "unsupported-version"
        detail = body["detail"]
        assert isinstance(detail, str)
        assert "1.5.6" in detail
        assert body["status"] == 422

        response = client.get("/missing")
        assert response.status_code == 404
        missing_body = json_obj(response)
        assert missing_body["code"] == "not-found"
        # camelCase policy: no snake_case keys on the wire
        assert "status_code" not in missing_body
