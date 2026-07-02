"""Plan preview (P2-T5, FR-U3/FR-Q4): pure, deterministic planner.

`build_plan(candidates, rails, …)` answers "what would dispatch next, and
why" without dispatching anything. Rails are *simulated* from the active
preset's stored posture (real rail counters/persistence arrive with P3-T1);
the §6.5 scheduling invariant is simulated unconditionally — it is
non-configurable. Candidates are evaluated in the order given (the ledger's
backlog order: bumps first, then score, then age), every candidate receives
an explained verdict, and identical inputs produce a byte-identical plan.

The `in_flight_*` inputs let Phase 3 feed real dispatched-window state into
the same function; in Observe mode they are empty.

Deliberately imports nothing from sqlalchemy/litestar/httpx.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal
from uuid import UUID

import msgspec

from perevoditarr.modules.dispatch.estimation import VolumeEstimate

DEFAULT_DISPATCH_WINDOW_K = 2  # PRD §7.2 default

type PairKey = tuple[UUID, str, int, str, str]


class SimulatedRails(msgspec.Struct, kw_only=True, frozen=True):
    """Rail posture the preview simulates (subset of §8.4 that is previewable
    without persisted counters; scheduling windows join with P3-T1)."""

    dispatch_window_k: int = DEFAULT_DISPATCH_WINDOW_K
    hourly_cap: int | None = None
    daily_cap: int | None = None
    weekly_cap: int | None = None
    budget_daily_characters: int | None = None


class PlanCandidate(msgspec.Struct, kw_only=True, frozen=True):
    intent_id: UUID
    bazarr_instance_id: UUID
    media_type: Literal["episode", "movie"]
    external_media_id: int
    sonarr_series_id: int | None = None
    display_title: str
    season: int | None = None
    episode_number: int | None = None
    source_language: str
    target_language: str
    forced: bool = False
    hi: bool = False
    priority: int
    bumped: bool = False
    # Scorer breakdown + profile from the stored decision trace (reasons).
    score_components: dict[str, int] | None = None
    profile_name: str | None = None
    estimate: VolumeEstimate


class Included(msgspec.Struct, kw_only=True, frozen=True, tag="included"):
    position: int  # 1-based dispatch order within the plan


class HeldByInvariant(msgspec.Struct, kw_only=True, frozen=True, tag="held_invariant"):
    rail: str = "invariant"
    detail: str


class HeldByWindow(msgspec.Struct, kw_only=True, frozen=True, tag="held_window"):
    rail: str = "window"
    detail: str


class HeldByCap(msgspec.Struct, kw_only=True, frozen=True, tag="held_cap"):
    rail: str  # cap_hourly | cap_daily | cap_weekly
    detail: str


class HeldByBudget(msgspec.Struct, kw_only=True, frozen=True, tag="held_budget"):
    rail: str = "budget"
    detail: str


class HeldByLimit(msgspec.Struct, kw_only=True, frozen=True, tag="held_limit"):
    detail: str


type PlanVerdict = (
    Included | HeldByInvariant | HeldByWindow | HeldByCap | HeldByBudget | HeldByLimit
)


class PlanItem(msgspec.Struct, kw_only=True, frozen=True):
    candidate: PlanCandidate
    verdict: PlanVerdict


class PlanTotals(msgspec.Struct, kw_only=True, frozen=True):
    evaluated: int
    included: int
    held: int
    estimated_lines: int  # included items only
    estimated_characters: int


class Plan(msgspec.Struct, kw_only=True, frozen=True):
    limit: int
    rails: SimulatedRails
    reference_time: datetime
    items: tuple[PlanItem, ...]
    totals: PlanTotals
    included_per_instance: dict[UUID, int]


def _pair_key(candidate: PlanCandidate) -> PairKey:
    """§6.5 identity: series-level for episodes, movie-level for movies."""
    if candidate.media_type == "episode":
        if candidate.sonarr_series_id is None:
            # Ledger-enforced invariant (P2-T2 upsert rejects such seeds);
            # a violation here means corrupted input, not a plannable item.
            raise ValueError(
                f"episode intent {candidate.intent_id} lacks sonarr_series_id"
            )
        return (
            candidate.bazarr_instance_id,
            "episode",
            candidate.sonarr_series_id,
            candidate.source_language,
            candidate.target_language,
        )
    return (
        candidate.bazarr_instance_id,
        "movie",
        candidate.external_media_id,
        candidate.source_language,
        candidate.target_language,
    )


def build_plan(
    candidates: Sequence[PlanCandidate],
    rails: SimulatedRails,
    *,
    limit: int,
    reference_time: datetime,
    in_flight_pair_keys: frozenset[PairKey] | None = None,
    in_flight_per_instance: Mapping[UUID, int] | None = None,
) -> Plan:
    window_used: dict[UUID, int] = dict(in_flight_per_instance or {})
    pair_keys: set[PairKey] = set(in_flight_pair_keys or ())
    included = 0
    consumed_characters = 0
    consumed_lines = 0
    items: list[PlanItem] = []

    caps: tuple[tuple[str, int | None], ...] = (
        ("cap_hourly", rails.hourly_cap),
        ("cap_daily", rails.daily_cap),
        ("cap_weekly", rails.weekly_cap),
    )

    for candidate in candidates:
        verdict = _evaluate(
            candidate,
            rails,
            caps,
            limit=limit,
            included=included,
            window_used=window_used,
            pair_keys=pair_keys,
            consumed_characters=consumed_characters,
        )
        if isinstance(verdict, Included):
            included += 1
            window_used[candidate.bazarr_instance_id] = (
                window_used.get(candidate.bazarr_instance_id, 0) + 1
            )
            pair_keys.add(_pair_key(candidate))
            consumed_characters += candidate.estimate.characters
            consumed_lines += candidate.estimate.lines
        items.append(PlanItem(candidate=candidate, verdict=verdict))

    instance_counts: dict[UUID, int] = {}
    for item in items:
        if isinstance(item.verdict, Included):
            key = item.candidate.bazarr_instance_id
            instance_counts[key] = instance_counts.get(key, 0) + 1

    return Plan(
        limit=limit,
        rails=rails,
        reference_time=reference_time,
        items=tuple(items),
        totals=PlanTotals(
            evaluated=len(items),
            included=included,
            held=len(items) - included,
            estimated_lines=consumed_lines,
            estimated_characters=consumed_characters,
        ),
        included_per_instance=instance_counts,
    )


def _evaluate(
    candidate: PlanCandidate,
    rails: SimulatedRails,
    caps: tuple[tuple[str, int | None], ...],
    *,
    limit: int,
    included: int,
    window_used: dict[UUID, int],
    pair_keys: set[PairKey],
    consumed_characters: int,
) -> PlanVerdict:
    # Check order mirrors rail fundamentality: the plan horizon, then the
    # non-configurable data-integrity invariant, then window, caps, budget.
    if included >= limit:
        return HeldByLimit(detail=f"beyond the next {limit} (plan horizon)")

    if _pair_key(candidate) in pair_keys:
        scope = (
            f"series `{candidate.display_title}`"
            if candidate.media_type == "episode"
            else f"movie `{candidate.display_title}`"
        )
        return HeldByInvariant(
            detail=(
                f"{scope} already has `{candidate.source_language}->"
                f"{candidate.target_language}` in the simulated window (§6.5:"
                " one in-flight per pair)"
            )
        )

    used = window_used.get(candidate.bazarr_instance_id, 0)
    if used >= rails.dispatch_window_k:
        return HeldByWindow(
            detail=(
                f"dispatch window full ({used}/{rails.dispatch_window_k}"
                " simulated in-flight for this instance)"
            )
        )

    for rail_name, cap in caps:
        if cap is not None and included >= cap:
            period = rail_name.removeprefix("cap_")
            return HeldByCap(rail=rail_name, detail=f"{period} cap {cap}/{cap}")

    budget = rails.budget_daily_characters
    if (
        budget is not None
        and consumed_characters + candidate.estimate.characters > budget
    ):
        return HeldByBudget(
            detail=(
                f"daily character budget would be exceeded"
                f" ({consumed_characters:,} + {candidate.estimate.characters:,}"
                f" > {budget:,})"
            )
        )

    return Included(position=included + 1)
