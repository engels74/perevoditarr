"""Mirror API controllers (P1-T5). Read paths hit the mirror only (FR-M1)."""

from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

from litestar import Controller, get, post
from litestar.openapi.spec import Example
from litestar.params import Parameter
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.schemas import Page
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.instances import (
    InstanceGateway,
    InstancesService,
)
from perevoditarr.modules.mirror.schemas import (
    CoverageStat,
    EpisodeRead,
    FreshnessRead,
    MovieRead,
    SeriesRead,
    SyncRunRead,
)
from perevoditarr.modules.mirror.service import MirrorService
from perevoditarr.modules.mirror.sync import MirrorSyncService

type _Limit = Annotated[int, Parameter(ge=1, le=500)]
type _Offset = Annotated[int, Parameter(ge=0)]
type _Search = Annotated[
    str | None,
    Parameter(
        description="Case-insensitive title search",
        examples=[Example(value="alpha show")],
    ),
]
type _MissingLanguage = Annotated[
    str | None,
    Parameter(
        description="Only items with this wanted target language (Bazarr code2)",
        examples=[Example(value="da")],
    ),
]


async def provide_mirror_service(db_session: AsyncSession) -> MirrorService:
    return MirrorService(db_session)


async def provide_mirror_sync_service(
    db_session: AsyncSession,
    auth_runtime: AuthRuntime,
    gateway: InstanceGateway,
    sse_bus: SseBus,
) -> MirrorSyncService:
    return MirrorSyncService(
        db_session,
        InstancesService(db_session, auth_runtime.secret_box),
        gateway,
        sse_bus,
    )


class MirrorController(Controller):
    path: str = "/mirror"
    tags: Sequence[str] | None = ("mirror",)

    @get("/series", operation_id="listSeries")
    async def series(
        self,
        mirror_service: MirrorService,
        instance_id: UUID | None = None,
        search: _Search = None,
        missing_language: _MissingLanguage = None,
        monitored: bool | None = None,
        limit: _Limit = 50,
        offset: _Offset = 0,
    ) -> Page[SeriesRead]:
        return await mirror_service.series_page(
            instance_id=instance_id,
            search=search,
            missing_language=missing_language,
            monitored=monitored,
            limit=limit,
            offset=offset,
        )

    @get("/series/{series_id:uuid}/episodes", operation_id="listSeriesEpisodes")
    async def series_episodes(
        self,
        series_id: UUID,
        mirror_service: MirrorService,
        limit: _Limit = 100,
        offset: _Offset = 0,
    ) -> Page[EpisodeRead]:
        return await mirror_service.series_episodes(
            series_id, limit=limit, offset=offset
        )

    @get("/movies", operation_id="listMovies")
    async def movies(
        self,
        mirror_service: MirrorService,
        instance_id: UUID | None = None,
        search: _Search = None,
        missing_language: _MissingLanguage = None,
        monitored: bool | None = None,
        limit: _Limit = 50,
        offset: _Offset = 0,
    ) -> Page[MovieRead]:
        return await mirror_service.movies_page(
            instance_id=instance_id,
            search=search,
            missing_language=missing_language,
            monitored=monitored,
            limit=limit,
            offset=offset,
        )

    @get("/coverage", operation_id="getCoverage")
    async def coverage(
        self, mirror_service: MirrorService, instance_id: UUID | None = None
    ) -> list[CoverageStat]:
        return await mirror_service.coverage(instance_id=instance_id)

    @get("/freshness", operation_id="getMirrorFreshness")
    async def freshness(
        self,
        mirror_service: MirrorService,
        instances_service: InstancesService,
    ) -> list[FreshnessRead]:
        instances = await instances_service.list_bazarr()
        return await mirror_service.freshness([i.id for i in instances])

    @get("/sync-runs", operation_id="listSyncRuns")
    async def sync_runs(
        self,
        mirror_service: MirrorService,
        instance_id: UUID | None = None,
        limit: _Limit = 20,
        offset: _Offset = 0,
    ) -> Page[SyncRunRead]:
        return await mirror_service.sync_runs(
            instance_id=instance_id, limit=limit, offset=offset
        )

    @post("/sync/{instance_id:uuid}", operation_id="runLibrarySync")
    async def run_sync(
        self,
        instance_id: UUID,
        mirror_sync_service: MirrorSyncService,
        mirror_service: MirrorService,
        full: bool = False,
    ) -> SyncRunRead:
        run = await mirror_sync_service.sync_library(instance_id, full=full)
        page = await mirror_service.sync_runs(instance_id=instance_id, limit=1)
        return next(item for item in page.items if item.id == run.id)

    @post("/sync/{instance_id:uuid}/wanted", operation_id="runWantedSync")
    async def run_wanted_sync(
        self,
        instance_id: UUID,
        mirror_sync_service: MirrorSyncService,
        mirror_service: MirrorService,
    ) -> SyncRunRead:
        run = await mirror_sync_service.sync_wanted(instance_id)
        page = await mirror_service.sync_runs(instance_id=instance_id, limit=1)
        return next(item for item in page.items if item.id == run.id)
