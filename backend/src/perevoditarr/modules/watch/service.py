"""Watch domain service (P5-T1): CRUD, credential encryption, refresh, index.

CRUD rides Advanced Alchemy async repositories; the refresh loop pulls activity
from every enabled source, aggregates to per-title signals, and rebuilds the
`watch_score` cache. Reads apply a hard TTL so a failing/removed source ages out
(ADR-0007). Watch data never touches the correctness plane.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import msgspec
from advanced_alchemy.exceptions import NotFoundError as AANotFoundError
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from msgspec import UNSET
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import ConflictError, NotFoundError, PerevoditarrError
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.integrations.watch import (
    WatchActivity,
    WatchMediaType,
    WatchSignal,
    WatchSourceProbe,
    WatchSourceType,
)
from perevoditarr.modules.watch.gateway import WatchGateway
from perevoditarr.modules.watch.models import WatchScore, WatchSource
from perevoditarr.modules.watch.schemas import (
    WatchRefreshResult,
    WatchSourceConfig,
    WatchSourceCreate,
    WatchSourceHealth,
    WatchSourceRead,
    WatchSourceTestResult,
    WatchSourceUpdate,
)
from perevoditarr.modules.watch.signal import WatchScoreIndex, aggregate_activity


def _decode_config(raw: dict[str, object] | None) -> WatchSourceConfig:
    if raw is None:
        return WatchSourceConfig()
    try:
        return msgspec.convert(raw, type=WatchSourceConfig)
    except msgspec.ValidationError:
        return WatchSourceConfig()


def _encode_struct(value: msgspec.Struct) -> dict[str, object]:
    return msgspec.json.decode(msgspec.json.encode(value), type=dict[str, object])


def _decode_health(raw: dict[str, object] | None) -> WatchSourceHealth | None:
    if raw is None:
        return None
    try:
        return msgspec.convert(raw, type=WatchSourceHealth)
    except msgspec.ValidationError:
        return None


def _source_type(value: str) -> WatchSourceType:
    if value in ("tautulli", "plex", "jellyfin"):
        return value
    # A row hand-edited to an unknown type is unusable; surface it explicitly.
    raise NotFoundError(f"unknown watch source type {value!r}")


def watch_source_read(row: WatchSource) -> WatchSourceRead:
    return WatchSourceRead(
        id=row.id,
        name=row.name,
        source_type=_source_type(row.source_type),
        url=row.url,
        has_credential=row.credential_encrypted is not None,
        enabled=row.enabled,
        config=_decode_config(row.config),
        health=_decode_health(row.health_snapshot),
        last_refreshed_at=row.last_refreshed_at,
        created_at=row.created_at,
    )


class WatchSourceRepository(SQLAlchemyAsyncRepository[WatchSource]):
    model_type: type[WatchSource] = WatchSource


class WatchService:
    def __init__(
        self, session: AsyncSession, secret_box: SecretBox, gateway: WatchGateway
    ) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box
        self.gateway: WatchGateway = gateway
        self.repo: WatchSourceRepository = WatchSourceRepository(session=session)

    # --- CRUD ------------------------------------------------------------

    async def list_sources(self) -> list[WatchSource]:
        return list(await self.repo.list(order_by=[("name", False)]))

    async def get_source(self, source_id: UUID) -> WatchSource:
        try:
            return await self.repo.get(source_id)
        except AANotFoundError as error:
            raise NotFoundError(f"watch source {source_id} not found") from error

    async def create_source(self, data: WatchSourceCreate) -> WatchSource:
        await self._ensure_unique_name(data.name)
        source = WatchSource(
            name=data.name,
            source_type=data.source_type,
            url=data.url.rstrip("/"),
            credential_encrypted=self.secret_box.encrypt_text(data.credential),
            enabled=data.enabled,
            config=_encode_struct(data.config),
        )
        self.session.add(source)
        await self.session.commit()
        return source

    async def update_source(
        self, source_id: UUID, data: WatchSourceUpdate
    ) -> WatchSource:
        source = await self.get_source(source_id)
        if data.name is not UNSET and data.name != source.name:
            await self._ensure_unique_name(data.name)
            source.name = data.name
        if data.url is not UNSET:
            source.url = data.url.rstrip("/")
        if data.credential is not UNSET:
            source.credential_encrypted = self.secret_box.encrypt_text(data.credential)
        if data.enabled is not UNSET:
            source.enabled = data.enabled
        if data.config is not UNSET:
            source.config = _encode_struct(data.config)
        await self.session.commit()
        return source

    async def delete_source(self, source_id: UUID) -> None:
        _ = await self.get_source(source_id)
        _ = await self.repo.delete(source_id)
        await self.session.commit()

    # --- probe / test ----------------------------------------------------

    async def test_config(
        self,
        *,
        source_type: WatchSourceType,
        url: str,
        credential: str,
        config: WatchSourceConfig,
    ) -> WatchSourceTestResult:
        client = self.gateway.client(
            source_type=source_type,
            url=url.rstrip("/"),
            credential=credential,
            config=config,
        )
        probe = await client.probe()
        return WatchSourceTestResult(
            reachable=probe.reachable,
            identity=probe.identity,
            version=probe.version,
            detail=probe.detail,
        )

    async def probe_source(self, source: WatchSource) -> WatchSourceProbe:
        """Live connectivity probe without persisting — used by the read-only
        doctor (N4). check_health() wraps this and stores the snapshot."""
        credential = self._credential(source)
        if credential is None:
            return WatchSourceProbe(reachable=False, detail="no credential stored")
        client = self.gateway.client(
            source_type=_source_type(source.source_type),
            url=source.url,
            credential=credential,
            config=_decode_config(source.config),
        )
        return await client.probe()

    async def check_health(self, source_id: UUID) -> WatchSource:
        source = await self.get_source(source_id)
        probe = await self.probe_source(source)
        self._store_health(source, probe, datetime.now(UTC))
        await self.session.commit()
        return source

    # --- refresh + index -------------------------------------------------

    async def refresh(
        self,
        *,
        window_days: int,
        frequent_min_plays: int,
        activity_limit: int,
        now: datetime | None = None,
    ) -> WatchRefreshResult:
        moment = now if now is not None else datetime.now(UTC)
        sources = [s for s in await self.list_sources() if s.enabled]
        activity_by_source: dict[str, list[WatchActivity]] = {}
        failed = 0
        for source in sources:
            credential = self._credential(source)
            if credential is None:
                failed += 1
                continue
            client = self.gateway.client(
                source_type=_source_type(source.source_type),
                url=source.url,
                credential=credential,
                config=_decode_config(source.config),
            )
            try:
                activity = await client.fetch_activity(
                    window_days=window_days, limit=activity_limit
                )
            except PerevoditarrError as error:
                failed += 1
                self._store_health(
                    source, WatchSourceProbe(reachable=False, detail=str(error)), moment
                )
                continue
            activity_by_source[source.name] = activity
            source.last_refreshed_at = moment
            self._store_health(source, WatchSourceProbe(reachable=True), moment)
        polled = len(sources)
        # All enabled sources failed: keep the existing cache, let the TTL age it
        # out rather than blanking every boost on a transient outage.
        if sources and not activity_by_source:
            await self.session.commit()
            return WatchRefreshResult(
                sources_polled=polled, sources_failed=failed, titles_scored=0
            )
        signals = aggregate_activity(
            activity_by_source,
            now_epoch=int(moment.timestamp()),
            recent_window_days=window_days,
            frequent_min_plays=frequent_min_plays,
        )
        _ = await self.session.execute(delete(WatchScore))
        self.session.add_all(
            [
                WatchScore(
                    media_type=signal.media_type,
                    title_key=signal.title_key,
                    title=signal.title,
                    year=signal.year,
                    watched_recently=signal.watched_recently,
                    watched_frequently=signal.watched_frequently,
                    watchlisted=signal.watchlisted,
                    sources=list(signal.sources),
                    refreshed_at=moment,
                )
                for signal in signals
            ]
        )
        await self.session.commit()
        return WatchRefreshResult(
            sources_polled=polled,
            sources_failed=failed,
            titles_scored=len(signals),
        )

    async def load_index(
        self, *, ttl_seconds: int, now: datetime | None = None
    ) -> WatchScoreIndex:
        return await load_watch_index(self.session, ttl_seconds=ttl_seconds, now=now)

    async def any_enabled(self) -> bool:
        return any(s.enabled for s in await self.list_sources())

    # --- helpers ---------------------------------------------------------

    def _credential(self, source: WatchSource) -> str | None:
        if source.credential_encrypted is None:
            return None
        return self.secret_box.decrypt_text(source.credential_encrypted)

    def _store_health(
        self, source: WatchSource, probe: WatchSourceProbe, moment: datetime
    ) -> None:
        source.health_snapshot = _encode_struct(
            WatchSourceHealth(
                reachable=probe.reachable,
                identity=probe.identity,
                version=probe.version,
                detail=probe.detail,
                checked_at=moment,
            )
        )

    async def _ensure_unique_name(self, name: str) -> None:
        existing = (
            await self.session.scalars(
                select(WatchSource.id).where(WatchSource.name == name)
            )
        ).first()
        if existing is not None:
            raise ConflictError(f"a watch source named {name!r} already exists")


# Default hard TTL for trusting cached scores when a caller has no configured
# value (discovery's fallback). The app threads the real setting through.
WATCH_SCORE_TTL_SECONDS = 86400


async def load_watch_index(
    session: AsyncSession, *, ttl_seconds: int, now: datetime | None = None
) -> WatchScoreIndex:
    """Build the read-only score index from cached rows fresher than the TTL.

    Pure read — no gateway/clients needed — so discovery can call it directly
    without constructing a WatchService (ADR-0007)."""
    moment = now if now is not None else datetime.now(UTC)
    cutoff = moment - timedelta(seconds=ttl_seconds)
    rows = list(
        await session.scalars(
            select(WatchScore).where(WatchScore.refreshed_at >= cutoff)
        )
    )
    index = WatchScoreIndex()
    for row in rows:
        media_type: WatchMediaType = "show" if row.media_type == "show" else "movie"
        index.add(
            media_type,
            row.title_key,
            row.year,
            WatchSignal(
                watched_recently=row.watched_recently,
                watched_frequently=row.watched_frequently,
                watchlisted=row.watchlisted,
                sources=tuple(row.sources),
            ),
        )
    return index
