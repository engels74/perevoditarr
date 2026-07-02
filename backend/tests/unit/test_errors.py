from litestar import get
from litestar.testing import create_test_client

from perevoditarr.core.errors import (
    NotFoundError,
    PerevoditarrError,
    UnsupportedVersionError,
    domain_exception_handler,
)


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
        body = response.json()
        assert body["code"] == "unsupported-version"
        assert "1.5.6" in body["detail"]
        assert body["status"] == 422

        response = client.get("/missing")
        assert response.status_code == 404
        assert response.json()["code"] == "not-found"
        # camelCase policy: no snake_case keys on the wire
        assert "status_code" not in response.json()
