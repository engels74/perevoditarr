"""Aggregate import of every ORM model module.

Alembic's env.py (and anything needing the full metadata) imports this module
so all tables register on the shared metadata. Each module adds its models
here as they land.
"""

from perevoditarr.modules.auth.models import ApiKey, AuthProviderConfig, User
from perevoditarr.modules.doctor.models import DoctorFinding, DoctorRun
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.intents.models import Intent, IntentEvent
from perevoditarr.modules.mirror.models import (
    Episode,
    Movie,
    Series,
    Subtitle,
    SyncRun,
    WantedSubtitle,
)
from perevoditarr.modules.notifications.models import NotificationRoute
from perevoditarr.modules.policy.models import (
    Exclusion,
    Override,
    Preset,
    ProfileAssignment,
    TranslationProfile,
)
from perevoditarr.modules.rails.models import RailState

__all__ = [
    "ApiKey",
    "AuthProviderConfig",
    "BazarrInstance",
    "DoctorFinding",
    "DoctorRun",
    "Episode",
    "Exclusion",
    "Intent",
    "IntentEvent",
    "LingarrInstance",
    "Movie",
    "NotificationRoute",
    "Override",
    "Preset",
    "ProfileAssignment",
    "RailState",
    "Series",
    "Subtitle",
    "SyncRun",
    "TranslationProfile",
    "User",
    "WantedSubtitle",
]
