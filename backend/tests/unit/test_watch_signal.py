"""Watch-signal aggregation and lookup index (P5-T1): pure domain logic."""

from perevoditarr.modules.integrations.watch import WatchActivity
from perevoditarr.modules.watch.signal import WatchScoreIndex, aggregate_activity

NOW = 1_720_000_000  # arbitrary fixed epoch
DAY = 86400


def _recent(offset_days: int) -> int:
    return NOW - offset_days * DAY


def test_recent_watch_produces_recent_signal() -> None:
    signals = aggregate_activity(
        {
            "tautulli": [
                WatchActivity(
                    media_type="show",
                    title="The Office",
                    last_watched_at=_recent(2),
                    play_count=1,
                )
            ]
        },
        now_epoch=NOW,
        recent_window_days=14,
        frequent_min_plays=3,
    )
    assert len(signals) == 1
    assert signals[0].watched_recently is True
    assert signals[0].watched_frequently is False
    assert signals[0].sources == ("tautulli",)


def test_old_low_play_activity_is_dropped() -> None:
    signals = aggregate_activity(
        {
            "plex": [
                WatchActivity(
                    media_type="show",
                    title="Old Show",
                    last_watched_at=_recent(90),
                    play_count=1,
                )
            ]
        },
        now_epoch=NOW,
        recent_window_days=14,
        frequent_min_plays=3,
    )
    assert signals == []


def test_play_counts_sum_across_sources_into_frequent() -> None:
    activity = WatchActivity(
        media_type="show", title="Popular", last_watched_at=_recent(90), play_count=2
    )
    signals = aggregate_activity(
        {"tautulli": [activity], "plex": [activity]},
        now_epoch=NOW,
        recent_window_days=14,
        frequent_min_plays=3,
    )
    assert len(signals) == 1
    assert signals[0].watched_frequently is True  # 2 + 2 >= 3
    assert signals[0].watched_recently is False
    assert signals[0].sources == ("plex", "tautulli")


def test_watchlist_only_entry_is_kept() -> None:
    signals = aggregate_activity(
        {
            "plex": [
                WatchActivity(
                    media_type="movie", title="Arrival", year=2016, watchlisted=True
                )
            ]
        },
        now_epoch=NOW,
        recent_window_days=14,
        frequent_min_plays=3,
    )
    assert len(signals) == 1
    assert signals[0].watchlisted is True
    assert signals[0].year == 2016


def test_titles_normalize_and_merge() -> None:
    signals = aggregate_activity(
        {
            "a": [
                WatchActivity(
                    media_type="show",
                    title="The Office (2005)",
                    last_watched_at=_recent(1),
                )
            ],
            "b": [WatchActivity(media_type="show", title="the  office", play_count=5)],
        },
        now_epoch=NOW,
        recent_window_days=14,
        frequent_min_plays=3,
    )
    assert len(signals) == 1  # both collapse to the same title key
    assert signals[0].watched_recently is True
    assert signals[0].watched_frequently is True


def test_index_lookup_show_and_movie_year_fallback() -> None:
    signals = aggregate_activity(
        {
            "a": [
                WatchActivity(
                    media_type="show", title="Severance", last_watched_at=_recent(1)
                ),
                WatchActivity(
                    media_type="movie",
                    title="Dune",
                    year=2021,
                    last_watched_at=_recent(1),
                ),
            ]
        },
        now_epoch=NOW,
        recent_window_days=14,
        frequent_min_plays=3,
    )
    index = WatchScoreIndex.from_signals(signals)
    assert index.signal_for("show", "severance") is not None
    # Exact year hits, wrong year falls back to the title-merged entry, and a
    # yearless lookup still resolves.
    assert index.signal_for("movie", "Dune", 2021) is not None
    assert index.signal_for("movie", "Dune", 1999) is not None
    assert index.signal_for("movie", "Dune") is not None
    assert index.signal_for("show", "Unknown") is None
    # A show identity never leaks into the movie namespace.
    assert index.signal_for("movie", "Severance") is None
