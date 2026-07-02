"""Plan-preview planner (P2-T5): determinism, §6.5 simulation, rail verdicts."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

import msgspec

from perevoditarr.modules.dispatch.estimation import VolumeEstimate
from perevoditarr.modules.dispatch.planning import (
    HeldByBudget,
    HeldByCap,
    HeldByInvariant,
    HeldByLimit,
    HeldByWindow,
    Included,
    PlanCandidate,
    SimulatedRails,
    build_plan,
)

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
INSTANCE = UUID("00000000-0000-0000-0000-000000000001")
OTHER_INSTANCE = UUID("00000000-0000-0000-0000-000000000002")
ESTIMATE = VolumeEstimate(lines=800, characters=36_000, basis="heuristic")


def _episode(
    *,
    intent_id: UUID | None = None,
    instance: UUID = INSTANCE,
    series: int = 11,
    episode: int = 101,
    source: str = "en",
    target: str = "da",
    priority: int = 50,
    estimate: VolumeEstimate = ESTIMATE,
) -> PlanCandidate:
    return PlanCandidate(
        intent_id=intent_id or uuid4(),
        bazarr_instance_id=instance,
        media_type="episode",
        external_media_id=episode,
        sonarr_series_id=series,
        display_title="Alpha Show",
        season=1,
        episode_number=episode % 100,
        source_language=source,
        target_language=target,
        priority=priority,
        estimate=estimate,
    )


def _movie(
    *,
    instance: UUID = INSTANCE,
    radarr_id: int = 7,
    source: str = "en",
    target: str = "da",
    priority: int = 50,
) -> PlanCandidate:
    return PlanCandidate(
        intent_id=uuid4(),
        bazarr_instance_id=instance,
        media_type="movie",
        external_media_id=radarr_id,
        display_title="Alpha Movie",
        source_language=source,
        target_language=target,
        priority=priority,
        estimate=ESTIMATE,
    )


def _verdicts(
    candidates: list[PlanCandidate],
    rails: SimulatedRails,
    *,
    limit: int = 10,
) -> list[object]:
    plan = build_plan(candidates, rails, limit=limit, reference_time=NOW)
    return [item.verdict for item in plan.items]


def test_identical_inputs_produce_byte_identical_plans() -> None:
    candidates = [
        _episode(intent_id=UUID(int=1), series=11, episode=101),
        _episode(intent_id=UUID(int=2), series=12, episode=201),
        _movie(),
    ]
    rails = SimulatedRails(dispatch_window_k=2, daily_cap=10)
    first = build_plan(candidates, rails, limit=5, reference_time=NOW)
    second = build_plan(candidates, rails, limit=5, reference_time=NOW)
    assert msgspec.json.encode(first) == msgspec.json.encode(second)


def test_empty_backlog_yields_empty_plan() -> None:
    plan = build_plan([], SimulatedRails(), limit=5, reference_time=NOW)
    assert plan.items == ()
    assert plan.totals.evaluated == 0
    assert plan.totals.included == 0
    assert plan.totals.estimated_characters == 0


def test_positions_follow_input_order() -> None:
    candidates = [
        _episode(series=11, episode=101),
        _episode(series=12, episode=201),
        _episode(series=13, episode=301),
    ]
    verdicts = _verdicts(candidates, SimulatedRails(dispatch_window_k=5))
    positions = [v.position for v in verdicts if isinstance(v, Included)]
    assert positions == [1, 2, 3]


def test_second_episode_of_same_series_and_pair_is_held_by_invariant() -> None:
    candidates = [
        _episode(series=11, episode=101),
        _episode(series=11, episode=102),  # same show, same en->da pair
    ]
    verdicts = _verdicts(candidates, SimulatedRails(dispatch_window_k=5))
    assert isinstance(verdicts[0], Included)
    held = verdicts[1]
    assert isinstance(held, HeldByInvariant)
    assert "en->da" in held.detail
    assert "§6.5" in held.detail


def test_same_series_different_target_is_not_held_by_invariant() -> None:
    candidates = [
        _episode(series=11, episode=101, target="da"),
        _episode(series=11, episode=102, target="sv"),
    ]
    verdicts = _verdicts(candidates, SimulatedRails(dispatch_window_k=5))
    assert all(isinstance(v, Included) for v in verdicts)


def test_same_movie_pair_is_held_by_invariant() -> None:
    candidates = [_movie(radarr_id=7), _movie(radarr_id=7)]
    verdicts = _verdicts(candidates, SimulatedRails(dispatch_window_k=5))
    assert isinstance(verdicts[0], Included)
    assert isinstance(verdicts[1], HeldByInvariant)


def test_invariant_is_scoped_per_instance() -> None:
    candidates = [
        _episode(instance=INSTANCE, series=11, episode=101),
        _episode(instance=OTHER_INSTANCE, series=11, episode=102),
    ]
    verdicts = _verdicts(candidates, SimulatedRails(dispatch_window_k=5))
    assert all(isinstance(v, Included) for v in verdicts)


def test_dispatch_window_holds_per_instance() -> None:
    candidates = [
        _episode(series=11, episode=101),
        _episode(series=12, episode=201),
        _episode(instance=OTHER_INSTANCE, series=13, episode=301),
    ]
    verdicts = _verdicts(candidates, SimulatedRails(dispatch_window_k=1))
    assert isinstance(verdicts[0], Included)
    held = verdicts[1]
    assert isinstance(held, HeldByWindow)
    assert "1/1" in held.detail
    # The other instance has its own window.
    assert isinstance(verdicts[2], Included)


def test_daily_cap_exhaustion_is_explained() -> None:
    candidates = [
        _episode(series=11, episode=101),
        _episode(series=12, episode=201),
    ]
    verdicts = _verdicts(candidates, SimulatedRails(dispatch_window_k=5, daily_cap=1))
    assert isinstance(verdicts[0], Included)
    held = verdicts[1]
    assert isinstance(held, HeldByCap)
    assert held.rail == "cap_daily"
    assert held.detail == "daily cap 1/1"


def test_tightest_cap_wins_the_explanation() -> None:
    candidates = [
        _episode(series=11, episode=101),
        _episode(series=12, episode=201),
    ]
    rails = SimulatedRails(dispatch_window_k=5, hourly_cap=1, daily_cap=5)
    held = _verdicts(candidates, rails)[1]
    assert isinstance(held, HeldByCap)
    assert held.rail == "cap_hourly"


def test_budget_exhaustion_is_explained() -> None:
    candidates = [
        _episode(series=11, episode=101),
        _episode(series=12, episode=201),
    ]
    rails = SimulatedRails(dispatch_window_k=5, budget_daily_characters=40_000)
    verdicts = _verdicts(candidates, rails)
    assert isinstance(verdicts[0], Included)  # 36k fits inside 40k
    held = verdicts[1]
    assert isinstance(held, HeldByBudget)
    assert "would be exceeded" in held.detail


def test_limit_horizon_holds_the_rest() -> None:
    candidates = [
        _episode(
            instance=OTHER_INSTANCE if index % 2 else INSTANCE,
            series=10 + index,
            episode=100 + index,
        )
        for index in range(4)
    ]
    verdicts = _verdicts(candidates, SimulatedRails(dispatch_window_k=5), limit=2)
    assert [type(v) for v in verdicts] == [
        Included,
        Included,
        HeldByLimit,
        HeldByLimit,
    ]


def test_totals_count_included_estimates_only() -> None:
    candidates = [
        _episode(series=11, episode=101),
        _episode(series=11, episode=102),  # held by invariant
    ]
    plan = build_plan(
        candidates, SimulatedRails(dispatch_window_k=5), limit=5, reference_time=NOW
    )
    assert plan.totals.included == 1
    assert plan.totals.held == 1
    assert plan.totals.estimated_characters == ESTIMATE.characters
    assert plan.totals.estimated_lines == ESTIMATE.lines
    assert plan.included_per_instance == {INSTANCE: 1}


def test_in_flight_state_seeds_the_simulation() -> None:
    """P3 seam: real dispatched intents occupy window slots and pair keys."""
    candidate = _episode(series=11, episode=101)
    pair_key: tuple[UUID, str, int, str, str] = (INSTANCE, "episode", 11, "en", "da")
    plan = build_plan(
        [candidate],
        SimulatedRails(dispatch_window_k=5),
        limit=5,
        reference_time=NOW,
        in_flight_pair_keys=frozenset({pair_key}),
    )
    assert isinstance(plan.items[0].verdict, HeldByInvariant)

    windowed = build_plan(
        [candidate],
        SimulatedRails(dispatch_window_k=1),
        limit=5,
        reference_time=NOW,
        in_flight_per_instance={INSTANCE: 1},
    )
    assert isinstance(windowed.items[0].verdict, HeldByWindow)


def test_media_type_annotation_is_literal() -> None:
    # Guards the PlanCandidate contract the service relies on.
    media: Literal["episode", "movie"] = _episode().media_type
    assert media == "episode"
