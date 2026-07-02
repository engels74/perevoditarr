"""Notification coalescing (P3-T5, FR-X1): per-(route, event) spam suppression.

A process-level singleton (created in app assembly like the SSE bus / lock
registry, NFR-3 single container): after a route fires for an event, further
sends of that same event to that route are suppressed until the coalescing
window elapses — so a breaker flapping or a cap staying pinned across many
passes yields one notification, not a storm. Volatile by design; a restart
simply re-arms every window.
"""

from datetime import datetime
from uuid import UUID

from perevoditarr.modules.notifications.events import NotificationEvent


class NotificationCoalescer:
    def __init__(self) -> None:
        self._last_sent: dict[tuple[UUID, NotificationEvent], datetime] = {}

    def should_send(
        self,
        route_id: UUID,
        event: NotificationEvent,
        *,
        now: datetime,
        window_seconds: int,
    ) -> bool:
        key = (route_id, event)
        last = self._last_sent.get(key)
        if last is not None and (now - last).total_seconds() < window_seconds:
            return False
        self._last_sent[key] = now
        return True
