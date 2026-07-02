"""Telemetry module public interface (P3-T4, §7.3 / NFR-7).

The liveness plane: Bazarr Socket.IO + Lingarr SignalR consumers with seamless
polling degradation, bridged to the UI over `telemetry.*` SSE topics and nudging
re-observation. TELEMETRY-ONLY — the correctness plane never imports this module
(enforced by `test_two_plane_separation`). App wiring takes the loop, the bridge,
the health registry, and the controller/DI.
"""

from perevoditarr.modules.telemetry.bridge import NudgeCallback, TelemetryBridge
from perevoditarr.modules.telemetry.controllers import (
    TelemetryController,
    TelemetryHealthService,
    provide_telemetry_health_service,
)
from perevoditarr.modules.telemetry.events import (
    JobProgress,
    RequestProgress,
    ResourceChanged,
    StreamHealth,
    StreamKind,
    TelemetryEvent,
)
from perevoditarr.modules.telemetry.health import TelemetryHealthRegistry
from perevoditarr.modules.telemetry.lifecycle import (
    StreamStatus,
    backoff_seconds,
    on_connected,
    on_failure,
)
from perevoditarr.modules.telemetry.parsing import (
    parse_bazarr_event,
    parse_lingarr_progress,
    parse_lingarr_request,
)
from perevoditarr.modules.telemetry.service import TelemetryService, telemetry_loop

__all__ = [
    "JobProgress",
    "NudgeCallback",
    "RequestProgress",
    "ResourceChanged",
    "StreamHealth",
    "StreamKind",
    "StreamStatus",
    "TelemetryBridge",
    "TelemetryController",
    "TelemetryEvent",
    "TelemetryHealthRegistry",
    "TelemetryHealthService",
    "TelemetryService",
    "backoff_seconds",
    "on_connected",
    "on_failure",
    "parse_bazarr_event",
    "parse_lingarr_progress",
    "parse_lingarr_request",
    "provide_telemetry_health_service",
    "telemetry_loop",
]
