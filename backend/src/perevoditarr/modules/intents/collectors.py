"""Evidence collectors (P2-T4): fresh reads of the durable planes (§6.8).

Three independently testable components, one per durable surface. All reads
go through the pooled integration clients (transport retries=0 — a failed
collection this pass is simply retried next pass, never re-tried in place).
Nothing here consumes Socket.IO/SignalR (§7.3), and nothing here writes.
"""

from collections.abc import Sequence

from perevoditarr.modules.integrations.bazarr import BazarrClient
from perevoditarr.modules.integrations.bazarr.schemas import (
    EpisodeHistoryItem,
    MovieHistoryItem,
    SubtitleFile,
)
from perevoditarr.modules.integrations.lingarr import (
    LingarrClient,
    TranslationRequestRecord,
)

# Keep seriesid[]/radarrid[] query strings well under URL-length limits.
_ID_CHUNK = 50
# Per-item history reads are bounded to the most recent entries; Bazarr
# returns newest-first, and older action-6 rows predate any current intent.
_HISTORY_LENGTH = 100


def _chunks(ids: Sequence[int]) -> list[list[int]]:
    ordered = sorted(set(ids))
    return [ordered[i : i + _ID_CHUNK] for i in range(0, len(ordered), _ID_CHUNK)]


class BazarrMetadataCollector:
    """Bulk subtitle-presence reads: batched by series/movie ids so a pass
    over N backlog intents costs O(distinct ids / chunk) requests, never
    O(N)."""

    def __init__(self, client: BazarrClient) -> None:
        self.client: BazarrClient = client

    async def episode_subtitles(
        self, series_ids: Sequence[int]
    ) -> dict[int, tuple[SubtitleFile, ...]]:
        """Fresh Bazarr metadata for all episodes of the given series, keyed
        by sonarr episode id."""
        collected: dict[int, tuple[SubtitleFile, ...]] = {}
        for chunk in _chunks(series_ids):
            for episode in await self.client.episodes(series_ids=chunk):
                collected[episode.sonarr_episode_id] = tuple(episode.subtitles)
        return collected

    async def movie_subtitles(
        self, radarr_ids: Sequence[int]
    ) -> dict[int, tuple[SubtitleFile, ...]]:
        collected: dict[int, tuple[SubtitleFile, ...]] = {}
        for chunk in _chunks(radarr_ids):
            page = await self.client.movies(radarr_ids=chunk)
            for movie in page.data:
                collected[movie.radarr_id] = tuple(movie.subtitles)
        return collected


class BazarrHistoryCollector:
    """Per-item translation-history reads (action 6 corroboration).

    Called only for items whose target subtitle actually appeared, so the
    call count is bounded by supersessions per pass, not backlog size.
    """

    def __init__(self, client: BazarrClient) -> None:
        self.client: BazarrClient = client

    async def episode_history(
        self, sonarr_episode_id: int
    ) -> tuple[EpisodeHistoryItem, ...]:
        page = await self.client.episodes_history(
            episode_id=sonarr_episode_id, length=_HISTORY_LENGTH
        )
        return tuple(page.data)

    async def movie_history(self, radarr_id: int) -> tuple[MovieHistoryItem, ...]:
        page = await self.client.movies_history(
            radarr_id=radarr_id, length=_HISTORY_LENGTH
        )
        return tuple(page.data)


class LingarrRequestCollector:
    """Durable TranslationRequest reads for §6.5-granularity matching.

    The active endpoint alone cannot carry §6.5 identity (no title/languages),
    so matching runs over full request records. Consumed by the evidence
    matchers here and by Phase 3's pre-dispatch guard and failure
    classification.
    """

    def __init__(self, client: LingarrClient) -> None:
        self.client: LingarrClient = client

    async def recent_requests(
        self, *, page_size: int = 100, max_pages: int = 5
    ) -> tuple[TranslationRequestRecord, ...]:
        records: list[TranslationRequestRecord] = []
        for page_number in range(1, max_pages + 1):
            page = await self.client.requests_page(
                page_number=page_number, page_size=page_size
            )
            records.extend(page.items)
            if len(records) >= page.total_count or not page.items:
                break
        return tuple(records)
