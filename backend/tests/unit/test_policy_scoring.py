"""Priority scorer (P2-T5): determinism, weight semantics, decay behavior."""

from datetime import UTC, datetime, timedelta

import msgspec
import pytest

from perevoditarr.modules.policy.resolver import PriorityWeights
from perevoditarr.modules.policy.scoring import ScoreFacts, score_intent

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
WEIGHTS = PriorityWeights()


def _facts(
    *,
    media_type: str = "episode",
    monitored: bool = True,
    age_hours: float = 0.0,
    series_ended: bool | None = False,
) -> ScoreFacts:
    assert media_type in ("episode", "movie")
    return ScoreFacts(
        media_type="episode" if media_type == "episode" else "movie",
        monitored=monitored,
        recency_anchor=NOW - timedelta(hours=age_hours),
        series_ended=series_ended,
    )


def test_deterministic_over_identical_inputs() -> None:
    first = score_intent(_facts(), WEIGHTS, now=NOW)
    second = score_intent(_facts(), WEIGHTS, now=NOW)
    assert msgspec.json.encode(first) == msgspec.json.encode(second)


def test_components_sum_to_total_and_keep_fixed_order() -> None:
    breakdown = score_intent(_facts(), WEIGHTS, now=NOW)
    assert sum(breakdown.components.values()) == breakdown.total
    assert list(breakdown.components) == ["base", "monitored", "continuing", "recency"]


def test_brand_new_item_gets_full_recency() -> None:
    breakdown = score_intent(_facts(age_hours=0), WEIGHTS, now=NOW)
    assert breakdown.components["recency"] == WEIGHTS.recency_max


def test_recency_halves_at_half_life() -> None:
    age = float(WEIGHTS.recency_half_life_hours)
    breakdown = score_intent(_facts(age_hours=age), WEIGHTS, now=NOW)
    assert breakdown.components["recency"] == WEIGHTS.recency_max // 2


def test_recency_decays_to_zero_for_ancient_items() -> None:
    breakdown = score_intent(_facts(age_hours=24 * 365 * 10), WEIGHTS, now=NOW)
    assert breakdown.components["recency"] == 0


def test_older_item_never_outscores_newer_identical_item() -> None:
    newer = score_intent(_facts(age_hours=1), WEIGHTS, now=NOW)
    older = score_intent(_facts(age_hours=500), WEIGHTS, now=NOW)
    assert newer.total > older.total


def test_future_anchor_clamps_to_now() -> None:
    facts = ScoreFacts(
        media_type="episode",
        monitored=True,
        recency_anchor=NOW + timedelta(days=2),  # unaired episode
        series_ended=False,
    )
    breakdown = score_intent(facts, WEIGHTS, now=NOW)
    assert breakdown.components["recency"] == WEIGHTS.recency_max


def test_monitored_bonus() -> None:
    monitored = score_intent(_facts(monitored=True), WEIGHTS, now=NOW)
    unmonitored = score_intent(_facts(monitored=False), WEIGHTS, now=NOW)
    assert monitored.components["monitored"] == WEIGHTS.monitored_bonus
    assert unmonitored.components["monitored"] == 0


@pytest.mark.parametrize(
    ("media_type", "series_ended", "expected"),
    [
        ("episode", False, 15),  # continuing series
        ("episode", True, 0),  # ended series
        ("episode", None, 0),  # unknown
        ("movie", None, 0),  # movies never get the bonus
        ("movie", False, 0),  # even a nonsensical flag is ignored for movies
    ],
)
def test_continuing_bonus_applies_only_to_continuing_series(
    media_type: str, series_ended: bool | None, expected: int
) -> None:
    breakdown = score_intent(
        _facts(media_type=media_type, series_ended=series_ended), WEIGHTS, now=NOW
    )
    assert breakdown.components["continuing"] == expected


def test_media_type_base_weights() -> None:
    weights = PriorityWeights(episode_base=5, movie_base=50)
    episode = score_intent(_facts(media_type="episode"), weights, now=NOW)
    movie = score_intent(_facts(media_type="movie"), weights, now=NOW)
    assert episode.components["base"] == 5
    assert movie.components["base"] == 50


def test_weight_change_flips_ordering() -> None:
    # Default weights: a fresh continuing episode beats an old movie.
    fresh_episode = _facts(media_type="episode", age_hours=0)
    old_movie = _facts(media_type="movie", age_hours=5000, series_ended=None)
    assert (
        score_intent(fresh_episode, WEIGHTS, now=NOW).total
        > score_intent(old_movie, WEIGHTS, now=NOW).total
    )
    # A movie-first profile flips the order.
    movie_first = PriorityWeights(movie_base=200)
    assert (
        score_intent(old_movie, movie_first, now=NOW).total
        > score_intent(fresh_episode, movie_first, now=NOW).total
    )


def test_scores_change_with_reference_time_only_via_recency() -> None:
    facts = _facts(age_hours=0)
    at_anchor = score_intent(facts, WEIGHTS, now=NOW)
    much_later = score_intent(facts, WEIGHTS, now=NOW + timedelta(days=365))
    assert at_anchor.components["recency"] > much_later.components["recency"]
    for key in ("base", "monitored", "continuing"):
        assert at_anchor.components[key] == much_later.components[key]
