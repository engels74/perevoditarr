"""Priority scorer (P2-T5, FR-Q4): pure domain logic, zero I/O imports.

Lives in the policy module because scoring *is* policy — the weights cascade
through `PolicyValues.priority_weights` like every other policy value, and
both discovery (stamping `Intent.priority`) and the dispatch planner sit
downstream of policy, so no import cycle can form.

Scores are deterministic over (item facts, weights, reference time) — the
clock is always passed in, never read here. Manual bump (`Intent.bumped_at`)
stays ledger-level and always outranks any score (backlog ordering, P2-T2).
"""

import math
from datetime import datetime
from typing import Literal

import msgspec

from perevoditarr.modules.policy.resolver import PriorityWeights


class ScoreFacts(msgspec.Struct, kw_only=True, frozen=True):
    """The item facts the scorer consumes — plain data from the mirror."""

    media_type: Literal["episode", "movie"]
    monitored: bool
    # Same recency anchor discovery uses for grace: air date when Bazarr ever
    # supplies one, else when the want first appeared in the mirror.
    recency_anchor: datetime
    # None = unknown (movies, or series without an ended flag) — no bonus.
    series_ended: bool | None = None


class ScoreBreakdown(msgspec.Struct, kw_only=True, frozen=True):
    total: int
    # Insertion order is fixed (base, monitored, continuing, recency) so
    # encoded breakdowns compare byte-identically in determinism tests.
    components: dict[str, int]


def score_intent(
    facts: ScoreFacts, weights: PriorityWeights, *, now: datetime
) -> ScoreBreakdown:
    base = weights.episode_base if facts.media_type == "episode" else weights.movie_base
    monitored = weights.monitored_bonus if facts.monitored else 0
    continuing = (
        weights.continuing_bonus
        if facts.media_type == "episode" and facts.series_ended is False
        else 0
    )
    age_hours = max(0.0, (now - facts.recency_anchor).total_seconds() / 3600.0)
    # math.pow keeps the checker-visible type float (float.__pow__ is Any).
    decay = math.pow(0.5, age_hours / weights.recency_half_life_hours)
    recency = round(weights.recency_max * decay)
    components = {
        "base": base,
        "monitored": monitored,
        "continuing": continuing,
        "recency": recency,
    }
    return ScoreBreakdown(total=sum(components.values()), components=components)
