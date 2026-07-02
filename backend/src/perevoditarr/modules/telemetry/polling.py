"""Polling fallback (P3-T4, NFR-7): telemetry without websockets.

When a stream is degraded (blocked by a proxy, upstream flakiness), the service
keeps the UI alive by polling the same durable-ish surfaces the sockets would
have pushed: Bazarr's jobs API for progress, Lingarr's active-requests list for
running translations. These emit the same telemetry events as the socket
consumers, so the UI is identical whether live or degraded. Read-only; nudges
flow through the bridge exactly as they would from a socket.
"""

from uuid import UUID

from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.lingarr import LingarrClient
from perevoditarr.modules.telemetry.bridge import TelemetryBridge
from perevoditarr.modules.telemetry.events import JobProgress, RequestProgress

# Bazarr job statuses worth surfacing as live progress.
_ACTIVE_JOB_STATUSES = frozenset({"running", "pending"})


async def poll_bazarr_once(
    client: BazarrClient, instance_id: UUID, bridge: TelemetryBridge
) -> int:
    """Emit a JobProgress per in-flight Bazarr job. Returns the count emitted."""
    emitted = 0
    for job in await client.jobs():
        if (job.status or "") not in _ACTIVE_JOB_STATUSES:
            continue
        await bridge.emit(
            instance_id,
            JobProgress(
                label=job.job_name or "job",
                value=job.progress_value,
                maximum=job.progress_max,
                message=job.progress_message,
            ),
        )
        emitted += 1
    return emitted


async def poll_lingarr_once(
    client: LingarrClient, instance_id: UUID, bridge: TelemetryBridge
) -> int:
    """Emit a RequestProgress per active Lingarr translation request."""
    emitted = 0
    for request in await client.active_requests():
        await bridge.emit(
            instance_id,
            RequestProgress(media_id=request.media_id, status=request.status),
        )
        emitted += 1
    return emitted
