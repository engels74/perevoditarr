"""Decision-trace vocabulary (P2-T2, FR-V1): pure msgspec tagged unions.

Every automated decision about an intent is recorded as a sequence of typed
rule-step records, persisted on the intent row and rendered human-readable:

    profile *Anime* → missing `da` → source `en` over `ja` by preference
    → grace passed → priority 3

The step vocabulary deliberately covers discovery (P2-T3), prioritization and
plan preview (P2-T5), and dispatch/rails (Phase 3) so the trace schema stays
stable across phases. Imports nothing from sqlalchemy/litestar/httpx.
"""

from collections.abc import Sequence
from typing import assert_never

import msgspec


class ProfileMatched(msgspec.Struct, tag="profile_matched", kw_only=True, frozen=True):
    profile_name: str
    layer: str  # global | preset | profile | override


class TargetMissing(msgspec.Struct, tag="target_missing", kw_only=True, frozen=True):
    language: str
    forced: bool = False
    hi: bool = False


class SourceElected(msgspec.Struct, tag="source_elected", kw_only=True, frozen=True):
    chosen: str
    considered: tuple[str, ...] = ()  # lower-preference candidates passed over


class GraceEvaluated(msgspec.Struct, tag="grace_evaluated", kw_only=True, frozen=True):
    passed: bool
    age_hours: int | None = None
    threshold_hours: int | None = None


class SkipEvaluated(msgspec.Struct, tag="skip_evaluated", kw_only=True, frozen=True):
    skipped: bool
    condition: str | None = None  # e.g. "unmonitored", "embedded target track"


class ExclusionMatched(
    msgspec.Struct, tag="exclusion_matched", kw_only=True, frozen=True
):
    kind: str  # series | movie | tag | language_pair
    rule_key: str


class PriorityAssigned(
    msgspec.Struct, tag="priority_assigned", kw_only=True, frozen=True
):
    score: int
    components: dict[str, int] | None = None  # scorer breakdown (P2-T5)
    # Cascade layer the weights came from (global|preset|profile|override) so
    # the trace shows *whose* weights produced the score (FR-Q4 provenance).
    weights_layer: str | None = None


class Withdrawn(msgspec.Struct, tag="withdrawn", kw_only=True, frozen=True):
    reason: str


class EvidenceObserved(
    msgspec.Struct, tag="evidence_observed", kw_only=True, frozen=True
):
    kind: str  # bazarr_metadata | bazarr_history | lingarr_request
    detail: str


class Dispatched(msgspec.Struct, tag="dispatched", kw_only=True, frozen=True):
    note: str | None = None


class BlockedByRail(msgspec.Struct, tag="blocked_by_rail", kw_only=True, frozen=True):
    rail: str  # cap | budget | window | breaker | invariant | pause
    detail: str


type TraceStep = (
    ProfileMatched
    | TargetMissing
    | SourceElected
    | GraceEvaluated
    | SkipEvaluated
    | ExclusionMatched
    | PriorityAssigned
    | Withdrawn
    | EvidenceObserved
    | Dispatched
    | BlockedByRail
)


def render_step(step: TraceStep) -> str:
    match step:
        case ProfileMatched(profile_name=name, layer="global"):
            return f"{name}"
        case ProfileMatched(profile_name=name):
            return f"profile *{name}*"
        case TargetMissing(language=language, forced=forced, hi=hi):
            flags = "".join((" (forced)" if forced else "", " (hi)" if hi else ""))
            return f"missing `{language}`{flags}"
        case SourceElected(chosen=chosen, considered=()):
            return f"source `{chosen}`"
        case SourceElected(chosen=chosen, considered=considered):
            passed_over = ", ".join(f"`{code}`" for code in considered)
            return f"source `{chosen}` over {passed_over} by preference"
        case GraceEvaluated(passed=True):
            return "grace passed"
        case GraceEvaluated(age_hours=age, threshold_hours=threshold) if (
            age is not None and threshold is not None
        ):
            return f"grace pending ({age}h of {threshold}h)"
        case GraceEvaluated():
            return "grace pending"
        case SkipEvaluated(skipped=True, condition=condition):
            return f"skipped: {condition or 'skip condition met'}"
        case SkipEvaluated():
            return "no skip condition"
        case ExclusionMatched(kind=kind, rule_key=rule_key):
            return f"excluded by {kind} rule `{rule_key}`"
        case PriorityAssigned(score=score):
            return f"priority {score}"
        case Withdrawn(reason=reason):
            return f"withdrawn: {reason}"
        case EvidenceObserved(kind=kind, detail=detail):
            return f"{kind.replace('_', ' ')}: {detail}"
        case Dispatched(note=None):
            return "dispatched"
        case Dispatched(note=note):
            return f"dispatched ({note})"
        case BlockedByRail(detail=detail):
            return f"blocked: {detail}"
    # Compile-time exhaustiveness: adding a TraceStep variant without a
    # render arm fails basedpyright here instead of TypeError-ing at render
    # time (`step` narrows to Never only when every variant returned above).
    assert_never(step)


def render_human(steps: Sequence[TraceStep]) -> str:
    return " → ".join(render_step(step) for step in steps)


def encode_trace(steps: Sequence[TraceStep]) -> list[dict[str, object]]:
    """Trace steps -> JSON-column shape (tag field included)."""
    return msgspec.json.decode(
        msgspec.json.encode(list(steps)), type=list[dict[str, object]]
    )


def decode_trace(raw: list[dict[str, object]] | None) -> tuple[TraceStep, ...]:
    """JSON column -> typed steps; rows written by a different build stay
    readable — an unknown step is dropped individually, the rest of the
    trace survives, and decoding never errors."""
    if raw is None:
        return ()
    steps: list[TraceStep] = []
    for item in raw:
        try:
            # Single-element list: `list[TraceStep]` is a real runtime type,
            # so convert stays fully typed (the bare union alias would not).
            steps.extend(msgspec.convert([item], type=list[TraceStep]))
        except msgspec.ValidationError:
            continue
    return tuple(steps)
