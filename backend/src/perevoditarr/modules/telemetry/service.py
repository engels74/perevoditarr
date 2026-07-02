"""Telemetry manager (P3-T4): consumers + seamless polling degradation.

Per enabled instance it runs the Socket.IO and SignalR consumers and a polling
loop that fills in whenever a stream is not live — so the UI shows the same
progress whether on websockets or polling, and upgrades back automatically the
moment a socket reconnects (NFR-7). `poll_degraded` is the testable core (it
polls exactly the streams that aren't live); the consumer tasks are the
best-effort live layer. Telemetry only ever nudges re-observation through the
bridge; it never drives a transition (§7.3).
"""

import asyncio
import contextlib
from uuid import UUID

from advanced_alchemy.extensions.litestar import SQLAlchemyAsyncConfig

from perevoditarr.core.logging import get_logger
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.instances import InstanceGateway, InstancesService
from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.lingarr import LingarrClient
from perevoditarr.modules.telemetry.bridge import TelemetryBridge
from perevoditarr.modules.telemetry.events import StreamKind
from perevoditarr.modules.telemetry.health import TelemetryHealthRegistry
from perevoditarr.modules.telemetry.parsing import (
    parse_lingarr_progress,
    parse_lingarr_request,
)
from perevoditarr.modules.telemetry.polling import poll_bazarr_once, poll_lingarr_once
from perevoditarr.modules.telemetry.signalr_consumer import LingarrSignalRConsumer
from perevoditarr.modules.telemetry.socketio_consumer import BazarrSocketConsumer

_logger = get_logger()

# Lingarr SignalR hub paths + methods (best-effort per §2.4).
_REQUESTS_HUB = ("/hub/translationRequests", "ReceiveTranslationRequest")
_PROGRESS_HUB = ("/hub/jobProgress", "ReceiveJobProgress")


def _live(
    health: TelemetryHealthRegistry, instance_id: UUID, stream: StreamKind
) -> bool:
    status = health.get(instance_id, stream)
    return status is not None and status.state == "live"


class TelemetryService:
    def __init__(
        self,
        gateway: InstanceGateway,
        secret_box: SecretBox,
        bridge: TelemetryBridge,
        health: TelemetryHealthRegistry,
    ) -> None:
        self.gateway: InstanceGateway = gateway
        self.secret_box: SecretBox = secret_box
        self.bridge: TelemetryBridge = bridge
        self.health: TelemetryHealthRegistry = health

    async def poll_degraded(
        self,
        instance_id: UUID,
        bazarr: BazarrClient,
        lingarr: LingarrClient | None,
    ) -> int:
        """Poll only the streams that are not currently live (seamless upgrade:
        a live socket suppresses its poll). Returns events emitted this tick."""
        emitted = 0
        if not _live(self.health, instance_id, "bazarr_socketio"):
            emitted += await poll_bazarr_once(bazarr, instance_id, self.bridge)
        if lingarr is not None and not _live(
            self.health, instance_id, "lingarr_signalr"
        ):
            emitted += await poll_lingarr_once(lingarr, instance_id, self.bridge)
        return emitted

    def start_consumers(
        self,
        instance_id: UUID,
        bazarr_url: str,
        bazarr_key: str,
        lingarr_url: str | None,
        lingarr_key: str | None,
    ) -> list[asyncio.Task[None]]:
        """Spawn the live socket consumers for one instance (best-effort layer)."""
        tasks = [
            asyncio.create_task(
                BazarrSocketConsumer(
                    instance_id, bazarr_url, bazarr_key, self.bridge, self.health
                ).run()
            )
        ]
        if lingarr_url is not None:
            requests_path, requests_method = _REQUESTS_HUB
            progress_path, progress_method = _PROGRESS_HUB
            tasks.append(
                asyncio.create_task(
                    LingarrSignalRConsumer(
                        instance_id,
                        f"{lingarr_url}{requests_path}",
                        lingarr_key,
                        requests_method,
                        parse_lingarr_request,
                        self.bridge,
                        self.health,
                    ).run()
                )
            )
            tasks.append(
                asyncio.create_task(
                    LingarrSignalRConsumer(
                        instance_id,
                        f"{lingarr_url}{progress_path}",
                        lingarr_key,
                        progress_method,
                        parse_lingarr_progress,
                        self.bridge,
                        self.health,
                    ).run()
                )
            )
        return tasks


async def telemetry_loop(
    alchemy: SQLAlchemyAsyncConfig,
    gateway: InstanceGateway,
    secret_box: SecretBox,
    bridge: TelemetryBridge,
    health: TelemetryHealthRegistry,
    poll_interval_seconds: int,
) -> None:
    """Start live consumers once, then poll degraded streams on each tick. On
    shutdown (task cancellation) the consumer tasks are cancelled too."""
    service = TelemetryService(gateway, secret_box, bridge, health)
    consumer_tasks: list[asyncio.Task[None]] = []
    started: set[UUID] = set()
    try:
        while True:
            async with alchemy.get_session() as session:
                instances = InstancesService(session, secret_box)
                for instance in await instances.list_bazarr():
                    if not instance.enabled:
                        continue
                    lingarr_url: str | None = None
                    lingarr_key: str | None = None
                    if instance.lingarr_instance_id is not None:
                        lingarr = await instances.get_lingarr(
                            instance.lingarr_instance_id
                        )
                        lingarr_url = lingarr.url
                        lingarr_key = instances.lingarr_api_key(lingarr)
                    bazarr_key = instances.bazarr_api_key(instance)
                    if instance.id not in started:
                        consumer_tasks.extend(
                            service.start_consumers(
                                instance.id,
                                instance.url,
                                bazarr_key,
                                lingarr_url,
                                lingarr_key,
                            )
                        )
                        started.add(instance.id)
                    bazarr_client = gateway.bazarr(instance.url, bazarr_key)
                    lingarr_client = (
                        gateway.lingarr(lingarr_url, lingarr_key)
                        if lingarr_url is not None
                        else None
                    )
                    with contextlib.suppress(Exception):
                        _ = await service.poll_degraded(
                            instance.id, bazarr_client, lingarr_client
                        )
            await asyncio.sleep(poll_interval_seconds)
    finally:
        for task in consumer_tasks:
            _ = task.cancel()
        for task in consumer_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
