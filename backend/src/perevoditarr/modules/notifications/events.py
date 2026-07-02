"""Notification event vocabulary (P3-T5, FR-X1): pure, transport-free.

The fixed routing matrix keys — a route subscribes to a subset of these — plus
the Apprise notify-type each maps to. A `NotificationMessage` is what the
orchestration layer hands the notifications service to fan out.
"""

from typing import Literal

import msgspec

type NotificationEvent = Literal[
    "breaker_tripped",
    "breaker_closed",
    "cap_reached",
    "quarantine_added",
    "doctor_critical",
    "daily_digest",
]

NOTIFICATION_EVENTS: tuple[NotificationEvent, ...] = (
    "breaker_tripped",
    "breaker_closed",
    "cap_reached",
    "quarantine_added",
    "doctor_critical",
    "daily_digest",
)

# Apprise NotifyType values (info | success | warning | failure).
_NOTIFY_TYPE: dict[NotificationEvent, str] = {
    "breaker_tripped": "failure",
    "breaker_closed": "success",
    "cap_reached": "warning",
    "quarantine_added": "warning",
    "doctor_critical": "failure",
    "daily_digest": "info",
}


class NotificationMessage(msgspec.Struct, frozen=True, kw_only=True):
    event: NotificationEvent
    title: str
    body: str

    @property
    def notify_type(self) -> str:
        return _NOTIFY_TYPE[self.event]
