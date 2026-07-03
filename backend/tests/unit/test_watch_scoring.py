"""Watch-aware scoring (P5-T1, FR-Q5): the watch component is additive, absent
without a signal, and honors the cascaded weights."""

from datetime import UTC, datetime

from perevoditarr.modules.integrations.watch import WatchSignal
from perevoditarr.modules.policy.resolver import PriorityWeights
from perevoditarr.modules.policy.scoring import ScoreFacts, score_intent, watch_boost

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
WEIGHTS = PriorityWeights()


def _facts(watch: WatchSignal | None) -> ScoreFacts:
    return ScoreFacts(
        media_type="episode",
        monitored=True,
        recency_anchor=NOW,
        series_ended=False,
        watch=watch,
    )


def test_no_signal_omits_watch_component() -> None:
    breakdown = score_intent(_facts(None), WEIGHTS, now=NOW)
    assert "watch" not in breakdown.components
    assert list(breakdown.components) == ["base", "monitored", "continuing", "recency"]


def test_recent_watch_adds_recent_bonus() -> None:
    signal = WatchSignal(watched_recently=True, sources=("Tautulli",))
    breakdown = score_intent(_facts(signal), WEIGHTS, now=NOW)
    assert breakdown.components["watch"] == WEIGHTS.watch_recent_bonus
    assert sum(breakdown.components.values()) == breakdown.total


def test_all_signals_sum_all_bonuses() -> None:
    signal = WatchSignal(
        watched_recently=True, watched_frequently=True, watchlisted=True
    )
    breakdown = score_intent(_facts(signal), WEIGHTS, now=NOW)
    expected = (
        WEIGHTS.watch_recent_bonus
        + WEIGHTS.watch_frequent_bonus
        + WEIGHTS.watchlist_bonus
    )
    assert breakdown.components["watch"] == expected


def test_watch_boost_lifts_total() -> None:
    without = score_intent(_facts(None), WEIGHTS, now=NOW)
    with_boost = score_intent(
        _facts(WatchSignal(watched_recently=True)), WEIGHTS, now=NOW
    )
    assert with_boost.total == without.total + WEIGHTS.watch_recent_bonus


def test_watch_boost_pure_helper_respects_zero_weights() -> None:
    weights = PriorityWeights(
        watch_recent_bonus=0, watch_frequent_bonus=0, watchlist_bonus=0
    )
    signal = WatchSignal(watched_recently=True, watchlisted=True)
    assert watch_boost(signal, weights) == 0
