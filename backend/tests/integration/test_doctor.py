"""Doctor runs end-to-end against the simulators (P1-T6)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from perevoditarr.core.db import build_alchemy_config, metadata
from perevoditarr.core.security import SecretBox
from perevoditarr.core.settings import AppSettings
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.doctor.models import DoctorFinding, DoctorRun
from perevoditarr.modules.doctor.service import DoctorService
from perevoditarr.modules.instances.schemas import (
    BazarrCapabilities,
    BazarrInstanceCreate,
    BazarrInstanceUpdate,
    LingarrInstanceCreate,
)
from perevoditarr.modules.instances.service import InstancesService
from tests.conftest import TEST_SECRET
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.scenario import Scenario


class _Harness:
    def __init__(
        self,
        service: DoctorService,
        scenario: Scenario,
        instances: InstancesService,
    ) -> None:
        self.service: DoctorService = service
        self.scenario: Scenario = scenario
        self.instances: InstancesService = instances


@pytest.fixture
async def harness(tmp_path: Path) -> AsyncIterator[_Harness]:
    settings = AppSettings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/doctor.db",
        secret_key=TEST_SECRET,
    )
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    await engine.dispose()
    alchemy = build_alchemy_config(settings)
    scenario = Scenario()
    gateway = SimulatorGateway(scenario)
    secret_box = SecretBox(TEST_SECRET)
    async with alchemy.get_session() as session:
        instances = InstancesService(session, secret_box)
        bazarr = await instances.create_bazarr(
            BazarrInstanceCreate(
                name="main", url="http://bazarr.test", api_key="bazarr-key"
            ),
            version="1.5.6",
            capabilities=BazarrCapabilities(),
        )
        lingarr = await instances.create_lingarr(
            LingarrInstanceCreate(
                name="shared", url="http://lingarr.test", api_key="lingarr-key"
            ),
            version="1.2.4",
        )
        _ = await instances.update_bazarr(
            bazarr.id, BazarrInstanceUpdate(lingarr_instance_id=lingarr.id)
        )
        service = DoctorService(session, secret_box, gateway, SseBus())
        yield _Harness(service, scenario, instances)


async def test_truthful_run_on_healthy_stack(harness: _Harness) -> None:
    run = await harness.service.run("manual")
    assert run.status == "completed"
    assert run.summary is not None
    assert run.summary["critical"] == 0
    check_ids = {f.check_id for f in run.findings}
    # report-style checks always present
    assert "FR-DR9" in check_ids
    assert "FR-DR10" in check_ids
    # mirror never synced yet => truthful warn (FR-DR11)
    dr11 = [f for f in run.findings if f.check_id == "FR-DR11"]
    assert any("never" in f.message for f in dr11)


async def test_lingarr_automation_flagged_critical(harness: _Harness) -> None:
    harness.scenario.set_lingarr_setting("automation_enabled", "true")
    run = await harness.service.run("manual")
    assert run.summary is not None
    assert run.summary["critical"] >= 1
    dr2 = [f for f in run.findings if f.check_id == "FR-DR2"]
    assert len(dr2) == 1
    assert dr2[0].severity == "critical"
    assert dr2[0].lingarr_instance_id is not None


async def test_runs_and_findings_persisted(harness: _Harness) -> None:
    first = await harness.service.run("manual")
    _ = await harness.service.run("scheduled")

    session = harness.service.session
    run_count = await session.scalar(select(func.count(DoctorRun.id)))
    assert run_count == 2
    finding_count = await session.scalar(
        select(func.count(DoctorFinding.id)).where(DoctorFinding.run_id == first.id)
    )
    assert finding_count == len(first.findings)

    latest = await harness.service.latest()
    assert latest is not None
    assert latest.trigger == "scheduled"
    assert latest.summary is not None


async def test_unreachable_lingarr_reported(harness: _Harness) -> None:
    # break the Lingarr API key so every call 401s
    harness.scenario.set_lingarr_setting("auth_enabled", "true")
    harness.scenario.set_lingarr_setting("api_key", "rotated-away")
    run = await harness.service.run("manual")
    dr1 = [f for f in run.findings if f.check_id == "FR-DR1"]
    assert any(f.severity == "critical" and "unreachable" in f.message for f in dr1)
