"""Lingarr SignalR consumer (P3-T4): pysignalr client.

One consumer per hub (TranslationRequestsHub, JobProgressHub). Each subscribes to
its hub method, maps the payload to a telemetry event via an injected parser, and
bridges it. Same lifecycle as the Socket.IO consumer: capped-backoff reconnect,
degrade to polling while down, never crash the app. `handle_args` is the testable
seam; hub URLs/method names are best-effort (§2.4).
"""

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pysignalr.client import SignalRClient

from perevoditarr.core.logging import get_logger
from perevoditarr.modules.integrations.lingarr.client import API_KEY_HEADER
from perevoditarr.modules.telemetry.bridge import TelemetryBridge
from perevoditarr.modules.telemetry.events import RequestProgress
from perevoditarr.modules.telemetry.health import TelemetryHealthRegistry
from perevoditarr.modules.telemetry.lifecycle import (
    StreamStatus,
    backoff_seconds,
    on_connected,
    on_failure,
)

_logger = get_logger()

type SignalRParser = Callable[[dict[str, object]], RequestProgress | None]
_STREAM = "lingarr_signalr"


class LingarrSignalRConsumer:
    def __init__(
        self,
        instance_id: UUID,
        hub_url: str,
        api_key: str | None,
        method: str,
        parser: SignalRParser,
        bridge: TelemetryBridge,
        health: TelemetryHealthRegistry,
        *,
        base_backoff: float = 2.0,
        cap_backoff: float = 120.0,
    ) -> None:
        self.instance_id: UUID = instance_id
        self.hub_url: str = hub_url
        self.api_key: str | None = api_key
        self.method: str = method
        self.parser: SignalRParser = parser
        self.bridge: TelemetryBridge = bridge
        self.health: TelemetryHealthRegistry = health
        self.base_backoff: float = base_backoff
        self.cap_backoff: float = cap_backoff

    async def handle_args(self, args: Sequence[object]) -> None:
        """Testable seam: SignalR delivers method args as a list; the first is the
        payload. Parse it and bridge."""
        payload = args[0] if args else None
        if not isinstance(payload, dict):
            return
        event = self.parser(cast("dict[str, object]", payload))
        if event is not None:
            await self.bridge.emit(self.instance_id, event)

    async def run(self) -> None:
        status = StreamStatus()
        headers = {API_KEY_HEADER: self.api_key} if self.api_key else {}

        async def mark_live() -> None:
            # pysignalr fires on_open only after negotiation + WS connect +
            # handshake succeed, so the stream is marked live on a real connection
            # rather than optimistically before client.run() does the network I/O
            # (mirrors the Socket.IO consumer's post-connect() ordering).
            nonlocal status
            status = on_connected(now=datetime.now(UTC))
            self.health.set(self.instance_id, _STREAM, status)

        while True:
            client = SignalRClient(self.hub_url, headers=headers)
            client.on(self.method, self.handle_args)
            client.on_open(mark_live)
            try:
                await client.run()
            except Exception as error:  # telemetry must never crash the app
                status = on_failure(status, now=datetime.now(UTC), detail=str(error))
                self.health.set(self.instance_id, _STREAM, status)
                _logger.debug("lingarr signalr degraded", error=str(error))
            await asyncio.sleep(
                backoff_seconds(
                    max(status.failures, 1),
                    base=self.base_backoff,
                    cap=self.cap_backoff,
                )
            )
