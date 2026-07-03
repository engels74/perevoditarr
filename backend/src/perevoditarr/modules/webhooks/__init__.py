"""Webhook ingestion module public interface (P5-T3, FR-X4)."""

from perevoditarr.modules.webhooks.controllers import (
    WebhookController,
    provide_webhook_runtime,
    provide_webhook_service,
)
from perevoditarr.modules.webhooks.models import WebhookSource
from perevoditarr.modules.webhooks.runtime import WebhookRuntime, WebhookTrigger
from perevoditarr.modules.webhooks.service import WebhookService, webhook_read

__all__ = [
    "WebhookController",
    "WebhookRuntime",
    "WebhookService",
    "WebhookSource",
    "WebhookTrigger",
    "provide_webhook_runtime",
    "provide_webhook_service",
    "webhook_read",
]
