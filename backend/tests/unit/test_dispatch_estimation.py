"""Volume estimator (P2-T5): actuals ladder, conservative bias, fallbacks."""

import math

from perevoditarr.modules.dispatch.estimation import (
    ACTUALS_HEADROOM,
    ACTUALS_MIN_SAMPLE,
    HEURISTIC_EPISODE_CHARACTERS,
    HEURISTIC_EPISODE_LINES,
    HEURISTIC_MOVIE_CHARACTERS,
    HEURISTIC_MOVIE_LINES,
    RollingActuals,
    actuals_from_statistics,
    estimate_intent,
)
from perevoditarr.modules.integrations.lingarr.schemas import LingarrStatistics

ACTUALS = RollingActuals(
    sample_files=100, lines_per_file=520.0, characters_per_file=21_000.0
)


def test_actuals_used_when_sample_is_large_enough() -> None:
    estimate = estimate_intent("episode", ACTUALS)
    assert estimate.basis == "actuals"
    assert estimate.lines == math.ceil(520.0 * ACTUALS_HEADROOM)
    assert estimate.characters == math.ceil(21_000.0 * ACTUALS_HEADROOM)


def test_actuals_estimates_carry_conservative_headroom() -> None:
    estimate = estimate_intent("movie", ACTUALS)
    assert estimate.lines > ACTUALS.lines_per_file
    assert estimate.characters > ACTUALS.characters_per_file


def test_small_sample_falls_back_to_heuristic() -> None:
    thin = RollingActuals(
        sample_files=ACTUALS_MIN_SAMPLE - 1,
        lines_per_file=520.0,
        characters_per_file=21_000.0,
    )
    assert estimate_intent("episode", thin).basis == "heuristic"


def test_no_actuals_falls_back_to_heuristic_per_media_type() -> None:
    episode = estimate_intent("episode", None)
    movie = estimate_intent("movie", None)
    assert (episode.lines, episode.characters) == (
        HEURISTIC_EPISODE_LINES,
        HEURISTIC_EPISODE_CHARACTERS,
    )
    assert (movie.lines, movie.characters) == (
        HEURISTIC_MOVIE_LINES,
        HEURISTIC_MOVIE_CHARACTERS,
    )
    # Conservative posture: movies estimate strictly higher than episodes.
    assert movie.characters > episode.characters


def test_statistics_with_no_files_yield_no_actuals() -> None:
    assert actuals_from_statistics(LingarrStatistics()) is None


def test_statistics_averages() -> None:
    stats = LingarrStatistics(
        total_lines_translated=5_000,
        total_files_translated=10,
        total_characters_translated=200_000,
    )
    actuals = actuals_from_statistics(stats)
    assert actuals is not None
    assert actuals.sample_files == 10
    assert actuals.lines_per_file == 500.0
    assert actuals.characters_per_file == 20_000.0
