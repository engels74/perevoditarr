"""Unit tests for the setup phase-derivation + checklist logic (P6-T1).

Exercises `_build_setup_status` directly with injected service counts so the
resume-state machine is verified without a database or live upstreams.
"""

from typing import cast

import pytest

from perevoditarr.modules.auth.controllers import (
    _build_setup_status,  # pyright: ignore[reportPrivateUsage]  # module-private derivation helper under test
)
from perevoditarr.modules.auth.security import AuthRuntime
from perevoditarr.modules.auth.service import AuthService
from perevoditarr.modules.instances.service import InstancesService
from perevoditarr.modules.notifications.service import NotificationsService


class _FakeAuthService:
    def __init__(self, *, user_count: int) -> None:
        self._user_count: int = user_count

    async def user_count(self) -> int:
        return self._user_count


class _FakeAuthRuntime:
    def __init__(self, *, completed: bool) -> None:
        self._completed: bool = completed

    async def is_setup_completed(self) -> bool:
        return self._completed


class _FakeInstancesService:
    def __init__(self, *, bazarr: int, lingarr: int) -> None:
        self._bazarr: int = bazarr
        self._lingarr: int = lingarr

    async def list_bazarr(self) -> list[object]:
        return [object()] * self._bazarr

    async def list_lingarr(self) -> list[object]:
        return [object()] * self._lingarr


class _FakeNotificationsService:
    def __init__(self, *, routes: int) -> None:
        self._routes: int = routes

    async def list_routes(self) -> list[object]:
        return [object()] * self._routes


async def _build(
    *,
    user_count: int,
    bazarr: int,
    lingarr: int,
    routes: int,
    completed: bool,
):
    return await _build_setup_status(
        auth_service=cast(
            AuthService, cast(object, _FakeAuthService(user_count=user_count))
        ),
        auth_runtime=cast(
            AuthRuntime, cast(object, _FakeAuthRuntime(completed=completed))
        ),
        instances_service=cast(
            InstancesService,
            cast(object, _FakeInstancesService(bazarr=bazarr, lingarr=lingarr)),
        ),
        notifications_service=cast(
            NotificationsService,
            cast(object, _FakeNotificationsService(routes=routes)),
        ),
    )


async def test_no_admin_derives_admin_phase() -> None:
    status = await _build(user_count=0, bazarr=0, lingarr=0, routes=0, completed=False)
    assert status.phase == "admin"
    assert status.required is True
    assert status.bootstrap_required is True
    assert status.completed is False
    assert status.checklist.has_admin is False


async def test_admin_without_bazarr_derives_bazarr_phase() -> None:
    status = await _build(user_count=1, bazarr=0, lingarr=0, routes=0, completed=False)
    assert status.phase == "bazarr"
    assert status.required is True
    assert status.bootstrap_required is False
    assert status.checklist.has_admin is True
    assert status.checklist.bazarr_count == 0


async def test_admin_with_bazarr_derives_finish_phase() -> None:
    status = await _build(user_count=1, bazarr=2, lingarr=0, routes=0, completed=False)
    assert status.phase == "finish"
    assert status.completed is False


@pytest.mark.parametrize(("lingarr", "routes"), [(0, 0), (3, 0), (0, 4), (2, 5)])
async def test_optional_steps_never_move_phase_off_finish(
    lingarr: int, routes: int
) -> None:
    # Once admin + >=1 Bazarr exist, optional lingarr/policy/notifications steps
    # never change the derived phase away from "finish".
    status = await _build(
        user_count=1, bazarr=1, lingarr=lingarr, routes=routes, completed=False
    )
    assert status.phase == "finish"


async def test_completed_derives_done_phase() -> None:
    status = await _build(user_count=1, bazarr=1, lingarr=1, routes=1, completed=True)
    assert status.phase == "done"
    assert status.required is False
    assert status.completed is True


async def test_checklist_reflects_injected_counts() -> None:
    status = await _build(user_count=1, bazarr=3, lingarr=2, routes=4, completed=False)
    assert status.checklist.has_admin is True
    assert status.checklist.bazarr_count == 3
    assert status.checklist.lingarr_count == 2
    assert status.checklist.notification_count == 4
