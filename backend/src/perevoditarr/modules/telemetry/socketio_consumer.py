"""Bazarr Socket.IO consumer (P3-T4): python-socketio client.

Subscribes to Bazarr's event stream and maps `{type, action, payload}` messages
to telemetry events. The connect loop retries with capped backoff on any failure
(NFR-7); while it is not connected the service serves the polling fallback. It
never crashes the app — only asyncio cancellation (shutdown) breaks the loop.
Message handling is extracted into `handle_message` so it is unit-testable
without a live socket; the upstream event name is best-effort (§2.4) — if it
differs, the stream simply stays on the polling fallback.
"""

import asyncio
import contextlib
from datetime import UTC, datetime
from uuid import UUID

import socketio  # pyright: ignore[reportMissingTypeStubs]  # python-socketio ships no stubs

from perevoditarr.core.logging import get_logger
from perevoditarr.modules.integrations.bazarr.client import API_KEY_HEADER
from perevoditarr.modules.telemetry.bridge import TelemetryBridge
from perevoditarr.modules.telemetry.health import TelemetryHealthRegistry
from perevoditarr.modules.telemetry.lifecycle import (
    StreamStatus,
    backoff_seconds,
    on_connected,
    on_failure,
)
from perevoditarr.modules.telemetry.parsing import parse_bazarr_event

_logger = get_logger()

# The Socket.IO event Bazarr pushes resource/task updates on (best-effort).
_BAZARR_EVENT = "data"
_STREAM = "bazarr_socketio"


class BazarrSocketConsumer:
    def __init__(
        self,
        instance_id: UUID,
        url: str,
        api_key: str,
        bridge: TelemetryBridge,
        health: TelemetryHealthRegistry,
        *,
        base_backoff: float = 2.0,
        cap_backoff: float = 120.0,
    ) -> None:
        self.instance_id: UUID = instance_id
        self.url: str = url
        self.api_key: str = api_key
        self.bridge: TelemetryBridge = bridge
        self.health: TelemetryHealthRegistry = health
        self.base_backoff: float = base_backoff
        self.cap_backoff: float = cap_backoff

    async def handle_message(self, raw: dict[str, object]) -> None:
        """Testable seam: parse one Bazarr message and bridge it."""
        event = parse_bazarr_event(raw)
        if event is not None:
            await self.bridge.emit(self.instance_id, event)

    async def _on_message(self, data: object) -> None:
        if isinstance(data, dict):
            await self.handle_message(data)  # pyright: ignore[reportUnknownArgumentType]  # untyped socket payload

    async def run(self) -> None:
        status = StreamStatus()
        while True:
            client: socketio.AsyncClient = socketio.AsyncClient(
                reconnection=False, logger=False, engineio_logger=False
            )
            _ = client.on(_BAZARR_EVENT, self._on_message)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]  # socketio untyped
            try:
                await client.connect(  # pyright: ignore[reportUnknownMemberType]  # socketio untyped
                    self.url, headers={API_KEY_HEADER: self.api_key}
                )
                status = on_connected(now=datetime.now(UTC))
                self.health.set(self.instance_id, _STREAM, status)
                await client.wait()
            except Exception as error:  # telemetry must never crash the app
                status = on_failure(status, now=datetime.now(UTC), detail=str(error))
                self.health.set(self.instance_id, _STREAM, status)
                _logger.debug("bazarr socket.io degraded", error=str(error))
            finally:
                with contextlib.suppress(Exception):
                    await client.disconnect()
            await asyncio.sleep(
                backoff_seconds(
                    max(status.failures, 1),
                    base=self.base_backoff,
                    cap=self.cap_backoff,
                )
            )
