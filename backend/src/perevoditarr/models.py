"""Aggregate import of every ORM model module.

Alembic's env.py (and anything needing the full metadata) imports this module
so all tables register on the shared metadata. Each module adds its models
here as they land.
"""

from perevoditarr.modules.auth.models import ApiKey, AuthProviderConfig, User
from perevoditarr.modules.doctor.models import DoctorFinding, DoctorRun
from perevoditarr.modules.instances.models import BazarrInstance, LingarrInstance
from perevoditarr.modules.mirror.models import (
    Episode,
    Movie,
    Series,
    Subtitle,
    SyncRun,
    WantedSubtitle,
)

__all__ = [
    "ApiKey",
    "AuthProviderConfig",
    "BazarrInstance",
    "DoctorFinding",
    "DoctorRun",
    "Episode",
    "LingarrInstance",
    "Movie",
    "Series",
    "Subtitle",
    "SyncRun",
    "User",
    "WantedSubtitle",
]
