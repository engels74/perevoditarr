"""Telemetry polling fallback (P3-T4, NFR-7): the degradation path driven
against the simulators, plus the seamless-upgrade suppression and the
stream-health API."""

from collections.abc import AsyncIterator, Iterator
from typing import override
from uuid import uuid4

import pytest
from litestar import Litestar
from litestar.testing import TestClient

from perevoditarr.core.security import SecretBox
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.telemetry.bridge import TelemetryBridge
from perevoditarr.modules.telemetry.health import TelemetryHealthRegistry
from perevoditarr.modules.telemetry.lifecycle import on_connected
from perevoditarr.modules.telemetry.service import TelemetryService
from tests.conftest import TEST_SECRET, complete_setup
from tests.integration.test_instances import SimulatorGateway
from tests.simulators.bazarr import SimJob
from tests.simulators.scenario import Scenario
from tests.support import json_obj

SECRET = SecretBox(TEST_SECRET)


class RecordingBus(SseBus):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[tuple[str, object]] = []

    @override
    def publish(self, topic: str, data: object) -> None:
        self.events.append((topic, data))
        super().publish(topic, data)


@pytest.fixture
async def scenario() -> AsyncIterator[Scenario]:
    s = Scenario()
    yield s
    await s.aclose()


def _service(
    scenario: Scenario, bus: SseBus, health: TelemetryHealthRegistry
) -> TelemetryService:
    gateway = SimulatorGateway(scenario)
    return TelemetryService(gateway, SECRET, TelemetryBridge(bus, None), health)


async def test_poll_degraded_emits_from_both_streams(scenario: Scenario) -> None:
    scenario.bazarr.jobs_running.append(
        SimJob(
            job_id=1,
            job_name="Translating EN to DA",
            status="running",
            progress_value=3,
            progress_max=10,
        )
    )
    _ = scenario.lingarr.add_request(
        media_id=5,
        title="Show",
        source_language="en",
        target_language="da",
        media_type="Episode",
        status="InProgress",
    )
    bus = RecordingBus()
    health = TelemetryHealthRegistry()
    service = _service(scenario, bus, health)
    gateway = SimulatorGateway(scenario)
    instance_id = uuid4()

    emitted = await service.poll_degraded(
        instance_id,
        gateway.bazarr("http://bazarr.test", scenario.bazarr.api_key),
        gateway.lingarr("http://lingarr.test", scenario.lingarr.api_key),
    )
    assert emitted == 2
    topics = {topic for topic, _ in bus.events}
    assert "telemetry.jobs" in topics
    assert "telemetry.requests" in topics


async def test_live_socket_suppresses_its_poll(scenario: Scenario) -> None:
    scenario.bazarr.jobs_running.append(
        SimJob(job_id=1, job_name="x", status="running")
    )
    bus = RecordingBus()
    health = TelemetryHealthRegistry()
    instance_id = uuid4()
    # Mark the Bazarr socket live → its poll is skipped (seamless upgrade).
    from datetime import UTC, datetime

    health.set(instance_id, "bazarr_socketio", on_connected(now=datetime.now(UTC)))
    service = _service(scenario, bus, health)
    gateway = SimulatorGateway(scenario)

    emitted = await service.poll_degraded(
        instance_id,
        gateway.bazarr("http://bazarr.test", scenario.bazarr.api_key),
        None,
    )
    assert emitted == 0


@pytest.fixture
def telemetry_client(
    app: Litestar, scenario: Scenario
) -> Iterator[TestClient[Litestar]]:
    app.state["gateway"] = SimulatorGateway(scenario)
    with TestClient(app=app) as client:
        complete_setup(client)
        yield client


async def test_telemetry_health_endpoint(
    telemetry_client: TestClient[Litestar],
) -> None:
    response = telemetry_client.get("/api/v1/telemetry/health")
    assert response.status_code == 200, response.text
    body = json_obj(response)
    assert isinstance(body["instances"], list)
