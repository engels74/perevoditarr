"""Mirror module public interface (P1-T5)."""

from perevoditarr.modules.mirror.controllers import (
    MirrorController,
    provide_mirror_service,
    provide_mirror_sync_service,
)
from perevoditarr.modules.mirror.models import (
    Episode,
    Movie,
    Series,
    Subtitle,
    SyncRun,
    WantedSubtitle,
)
from perevoditarr.modules.mirror.scheduler import library_sync_loop, wanted_sync_loop
from perevoditarr.modules.mirror.service import MirrorService
from perevoditarr.modules.mirror.sync import MirrorSyncService

__all__ = [
    "Episode",
    "MirrorController",
    "MirrorService",
    "MirrorSyncService",
    "Movie",
    "Series",
    "Subtitle",
    "SyncRun",
    "WantedSubtitle",
    "library_sync_loop",
    "provide_mirror_service",
    "provide_mirror_sync_service",
    "wanted_sync_loop",
]
