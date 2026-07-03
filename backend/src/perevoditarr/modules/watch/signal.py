"""Watch-signal aggregation and lookup index (P5-T1): pure domain logic.

`aggregate_activity` folds raw `WatchActivity` from every enabled source into
one `AggregatedSignal` per §6.5 title identity — the rows the refresh loop
upserts into `watch_score`. `WatchScoreIndex` is the read side: discovery loads
the cached rows once per pass and looks up each candidate by normalized title.

Imports nothing from sqlalchemy/httpx: the service converts activity/rows into
these plain structs before calling in.
"""

import msgspec

from perevoditarr.modules.integrations.watch import (
    WatchActivity,
    WatchMediaType,
    WatchSignal,
    normalize_title,
)

type _Key = tuple[WatchMediaType, str, int]


class AggregatedSignal(msgspec.Struct, kw_only=True, frozen=True):
    """One title's fully-aggregated watch signal, ready to persist."""

    media_type: WatchMediaType
    title_key: str
    title: str
    year: int  # 0 for shows / unknown
    watched_recently: bool
    watched_frequently: bool
    watchlisted: bool
    sources: tuple[str, ...]


class _Accumulator:
    __slots__: tuple[str, ...] = (
        "last_watched_at",
        "play_count",
        "sources",
        "title",
        "watchlisted",
    )

    def __init__(self, title: str) -> None:
        self.title: str = title
        self.last_watched_at: int | None = None
        self.play_count: int = 0
        self.watchlisted: bool = False
        self.sources: set[str] = set()


def aggregate_activity(
    activity_by_source: dict[str, list[WatchActivity]],
    *,
    now_epoch: int,
    recent_window_days: int,
    frequent_min_plays: int,
) -> list[AggregatedSignal]:
    recent_cutoff = now_epoch - recent_window_days * 86400
    acc: dict[_Key, _Accumulator] = {}
    for source_name, activities in activity_by_source.items():
        for item in activities:
            year = (item.year or 0) if item.media_type == "movie" else 0
            key: _Key = (item.media_type, normalize_title(item.title), year)
            entry = acc.get(key)
            if entry is None:
                entry = _Accumulator(item.title)
                acc[key] = entry
            if item.last_watched_at is not None and (
                entry.last_watched_at is None
                or item.last_watched_at > entry.last_watched_at
            ):
                entry.last_watched_at = item.last_watched_at
            entry.play_count += max(0, item.play_count)
            entry.watchlisted = entry.watchlisted or item.watchlisted
            entry.sources.add(source_name)
    signals: list[AggregatedSignal] = []
    for (media_type, title_key, year), entry in acc.items():
        recently = (
            entry.last_watched_at is not None and entry.last_watched_at >= recent_cutoff
        )
        frequently = entry.play_count >= frequent_min_plays
        # A pure watchlist entry (no plays) still deserves a row so the boost applies.
        if not (recently or frequently or entry.watchlisted):
            continue
        signals.append(
            AggregatedSignal(
                media_type=media_type,
                title_key=title_key,
                title=entry.title,
                year=year,
                watched_recently=recently,
                watched_frequently=frequently,
                watchlisted=entry.watchlisted,
                sources=tuple(sorted(entry.sources)),
            )
        )
    return signals


class WatchScoreIndex:
    """Read-side lookup over cached watch scores, built once per discovery pass.

    Movie lookups fall back title→year loosely (year mismatch or a source that
    reported no year still boosts), matching the soft-signal intent (ADR-0007).
    """

    def __init__(self) -> None:
        self._exact: dict[_Key, WatchSignal] = {}
        self._by_title: dict[tuple[WatchMediaType, str], WatchSignal] = {}

    @classmethod
    def from_signals(cls, signals: list[AggregatedSignal]) -> WatchScoreIndex:
        index = cls()
        for signal in signals:
            index.add(
                signal.media_type,
                signal.title_key,
                signal.year,
                WatchSignal(
                    watched_recently=signal.watched_recently,
                    watched_frequently=signal.watched_frequently,
                    watchlisted=signal.watchlisted,
                    sources=signal.sources,
                ),
            )
        return index

    def add(
        self,
        media_type: WatchMediaType,
        title_key: str,
        year: int,
        signal: WatchSignal,
    ) -> None:
        self._exact[(media_type, title_key, year)] = signal
        self._merge_title((media_type, title_key), signal)

    def _merge_title(self, key: tuple[WatchMediaType, str], value: WatchSignal) -> None:
        current = self._by_title.get(key)
        if current is None:
            self._by_title[key] = value
            return
        self._by_title[key] = WatchSignal(
            watched_recently=current.watched_recently or value.watched_recently,
            watched_frequently=current.watched_frequently or value.watched_frequently,
            watchlisted=current.watchlisted or value.watchlisted,
            sources=tuple(sorted({*current.sources, *value.sources})),
        )

    def signal_for(
        self, media_type: WatchMediaType, title: str, year: int | None = None
    ) -> WatchSignal | None:
        title_key = normalize_title(title)
        if media_type == "show":
            return self._exact.get(("show", title_key, 0))
        if year is not None:
            exact = self._exact.get(("movie", title_key, year))
            if exact is not None:
                return exact
        return self._by_title.get(("movie", title_key))

    def __len__(self) -> int:
        return len(self._exact)
