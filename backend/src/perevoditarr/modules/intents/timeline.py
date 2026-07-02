"""Per-item timeline (P4-T2, FR-V4): stitch the durable planes into one
chronological stream for a single intent.

Sources, all §6.8-durable: the intent's own `intent_event` audit trail, its
Bazarr translation history (action 6), the matching Lingarr request records
(§6.5 granularity), and the pass-through-action audit rows. Upstream reads go
through the pooled clients; an unreachable Bazarr/Lingarr degrades to "that
source unavailable" and is flagged in the response — never an error (the
telemetry-plane posture, §7.3, applied to a read-only view).
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from perevoditarr.core.errors import NotFoundError, PerevoditarrError
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.instances import (
    BazarrInstance,
    InstanceGateway,
    InstancesService,
)
from perevoditarr.modules.integrations.bazarr.schemas import (
    HISTORY_ACTION_TRANSLATED,
)
from perevoditarr.modules.intents.collectors import (
    BazarrHistoryCollector,
    LingarrRequestCollector,
)
from perevoditarr.modules.intents.evidence import (
    matching_lingarr_records_episode,
    matching_lingarr_records_movie,
    parse_history_timestamp,
)
from perevoditarr.modules.intents.models import Intent, PassthroughAction
from perevoditarr.modules.intents.schemas import (
    TimelineBazarrHistoryEntry,
    TimelineEntryDto,
    TimelineIntentEventEntry,
    TimelineLingarrRequestEntry,
    TimelinePassthroughEntry,
    TimelineResponse,
)
from perevoditarr.modules.intents.service import intent_read

_FAR_FUTURE = datetime.max.replace(tzinfo=UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _sort_key(entry: TimelineEntryDto) -> tuple[bool, datetime]:
    # Ascending by timestamp; unknown-time entries sort last, stably.
    at = _aware(entry.at)
    return (at is None, at or _FAR_FUTURE)


class TimelineService:
    def __init__(
        self, session: AsyncSession, secret_box: SecretBox, gateway: InstanceGateway
    ) -> None:
        self.session: AsyncSession = session
        self.gateway: InstanceGateway = gateway
        self.instances: InstancesService = InstancesService(session, secret_box)

    async def timeline(self, intent_id: UUID) -> TimelineResponse:
        intent = (
            await self.session.scalars(
                select(Intent)
                .where(Intent.id == intent_id)
                .options(selectinload(Intent.events))
            )
        ).first()
        if intent is None:
            raise NotFoundError(f"intent {intent_id} not found")

        entries: list[TimelineEntryDto] = [
            TimelineIntentEventEntry(
                at=_aware(event.created_at) or _FAR_FUTURE,
                actor=event.actor,
                from_state=event.from_state,
                to_state=event.to_state,
                reason=event.reason,
            )
            for event in intent.events
        ]
        entries.extend(await self._passthrough_entries(intent_id))

        instance = await self.instances.get_bazarr(intent.bazarr_instance_id)
        bazarr_available = await self._append_bazarr_history(intent, instance, entries)
        lingarr_available = await self._append_lingarr_requests(
            intent, instance, entries
        )

        entries.sort(key=_sort_key)
        return TimelineResponse(
            intent=intent_read(intent),
            bazarr_history_available=bazarr_available,
            lingarr_available=lingarr_available,
            entries=entries,
        )

    async def _passthrough_entries(self, intent_id: UUID) -> list[TimelineEntryDto]:
        rows = (
            await self.session.scalars(
                select(PassthroughAction)
                .where(PassthroughAction.intent_id == intent_id)
                .order_by(PassthroughAction.created_at)
            )
        ).all()
        return [
            TimelinePassthroughEntry(
                at=_aware(row.created_at) or _FAR_FUTURE,
                action=row.action,
                actor=row.actor,
                status=row.status,
                detail=row.detail,
                lingarr_request_id=row.lingarr_request_id,
            )
            for row in rows
        ]

    async def _append_bazarr_history(
        self,
        intent: Intent,
        instance: BazarrInstance,
        entries: list[TimelineEntryDto],
    ) -> bool:
        try:
            client = self.gateway.bazarr(
                instance.url, self.instances.bazarr_api_key(instance)
            )
            collector = BazarrHistoryCollector(client)
            if intent.media_type == "episode":
                items = await collector.episode_history(intent.external_media_id)
                history = [
                    TimelineBazarrHistoryEntry(
                        at=parse_history_timestamp(item.timestamp),
                        action=item.action,
                        description=item.description,
                        language=item.language.code2 if item.language else None,
                        subtitles_path=item.subtitles_path,
                    )
                    for item in items
                    if item.action == HISTORY_ACTION_TRANSLATED
                ]
            else:
                movie_items = await collector.movie_history(intent.external_media_id)
                history = [
                    TimelineBazarrHistoryEntry(
                        at=parse_history_timestamp(item.timestamp),
                        action=item.action,
                        description=item.description,
                        language=item.language.code2 if item.language else None,
                        subtitles_path=item.subtitles_path,
                    )
                    for item in movie_items
                    if item.action == HISTORY_ACTION_TRANSLATED
                ]
        except PerevoditarrError:
            return False
        entries.extend(history)
        return True

    async def _append_lingarr_requests(
        self,
        intent: Intent,
        instance: BazarrInstance,
        entries: list[TimelineEntryDto],
    ) -> bool:
        if instance.lingarr_instance_id is None:
            return False
        try:
            lingarr = await self.instances.get_lingarr(instance.lingarr_instance_id)
            client = self.gateway.lingarr(
                lingarr.url, self.instances.lingarr_api_key(lingarr)
            )
            # Cold-path per-item lookup: scan a deliberately wider bounded
            # window (100 x 20 = 2000) than the shared 500-record default, so
            # older intents on large Lingarr instances still resolve their
            # matching request by title+language. Bounded on purpose — this is
            # a telemetry-plane read (§7.3) where a miss is a cosmetic gap,
            # never a wrong state transition, so the window stays finite to
            # keep upstream request cost sane rather than paging unbounded.
            records = await LingarrRequestCollector(client).recent_requests(
                page_size=100, max_pages=20
            )
        except PerevoditarrError:
            return False
        if intent.media_type == "episode":
            matched = matching_lingarr_records_episode(
                records,
                display_title=intent.display_title,
                source_language=intent.source_language,
                target_language=intent.target_language,
            )
        else:
            matched = matching_lingarr_records_movie(
                records,
                radarr_id=intent.external_media_id,
                display_title=intent.display_title,
                source_language=intent.source_language,
                target_language=intent.target_language,
            )
        entries.extend(
            TimelineLingarrRequestEntry(
                at=_aware(record.created_at),
                request_id=record.id,
                status=record.status,
                source_language=record.source_language,
                target_language=record.target_language,
                error_message=record.error_message,
                completed_at=_aware(record.completed_at),
                active=(record.status or "") in ("Pending", "InProgress"),
            )
            for record in matched
        )
        return True
