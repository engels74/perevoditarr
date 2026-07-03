"""Aggregate import of every ORM model module.

Alembic's env.py (and anything needing the full metadata) imports this module
so all tables register on the shared metadata. Each module adds its models
here as they land.
"""

from perevoditarr.modules.auth.models import ApiKey, AuthProviderConfig, User
from perevoditarr.modules.doctor.models import DoctorFinding, DoctorRun
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.intents.models import (
    Intent,
    IntentEvent,
    PassthroughAction,
)
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
from perevoditarr.modules.stats.models import (
    LingarrActuals,
    StatsDaily,
    StatsLanguageDaily,
)

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
    "LingarrActuals",
    "LingarrInstance",
    "Movie",
    "NotificationRoute",
    "Override",
    "PassthroughAction",
    "Preset",
    "ProfileAssignment",
    "RailState",
    "Series",
    "StatsDaily",
    "StatsLanguageDaily",
    "Subtitle",
    "SyncRun",
    "TranslationProfile",
    "User",
    "WantedSubtitle",
]
