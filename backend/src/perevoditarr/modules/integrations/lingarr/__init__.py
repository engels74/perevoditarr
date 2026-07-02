"""Lingarr integration public interface (P1-T3)."""

from perevoditarr.modules.integrations.lingarr.client import (
    DOCTOR_SETTING_KEYS,
    MIN_LINGARR_VERSION,
    LingarrClient,
    ensure_supported_version,
)
from perevoditarr.modules.integrations.lingarr.schemas import (
    ACTIVE_STATUSES,
    ActiveTranslation,
    LingarrStatistics,
    PagedTranslationRequests,
    TranslationRequestRecord,
    VersionInfo,
)

__all__ = [
    "ACTIVE_STATUSES",
    "DOCTOR_SETTING_KEYS",
    "MIN_LINGARR_VERSION",
    "ActiveTranslation",
    "LingarrClient",
    "LingarrStatistics",
    "PagedTranslationRequests",
    "TranslationRequestRecord",
    "VersionInfo",
    "ensure_supported_version",
]
