"""Notifications module public interface (P3-T5, FR-X1).

App wiring takes the controller/DI and the process-singleton coalescer; the
orchestration forwarders build a `NotificationMessage` and call `notify`.
"""

from perevoditarr.modules.notifications.coalescer import NotificationCoalescer
from perevoditarr.modules.notifications.controllers import (
    NotificationsController,
    provide_notifications_service,
)
from perevoditarr.modules.notifications.events import (
    NOTIFICATION_EVENTS,
    NotificationEvent,
    NotificationMessage,
)
from perevoditarr.modules.notifications.models import NotificationRoute
from perevoditarr.modules.notifications.service import (
    NotificationsService,
    apprise_send,
)

__all__ = [
    "NOTIFICATION_EVENTS",
    "NotificationCoalescer",
    "NotificationEvent",
    "NotificationMessage",
    "NotificationRoute",
    "NotificationsController",
    "NotificationsService",
    "apprise_send",
    "provide_notifications_service",
]
