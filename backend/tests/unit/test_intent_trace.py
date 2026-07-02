"""Decision-trace rendering and round-trip (P2-T2, FR-V1)."""

from perevoditarr.modules.intents.trace import (
    BlockedByRail,
    Dispatched,
    EvidenceObserved,
    ExclusionMatched,
    GraceEvaluated,
    PriorityAssigned,
    ProfileMatched,
    SkipEvaluated,
    SourceElected,
    TargetMissing,
    TraceStep,
    Withdrawn,
    decode_trace,
    encode_trace,
    render_human,
    render_step,
)


def test_prd_example_renders_verbatim() -> None:
    steps: list[TraceStep] = [
        ProfileMatched(profile_name="Anime", layer="profile"),
        TargetMissing(language="da"),
        SourceElected(chosen="en", considered=("ja",)),
        GraceEvaluated(passed=True),
        PriorityAssigned(score=3),
    ]
    assert render_human(steps) == (
        "profile *Anime* → missing `da` → source `en` over `ja` by preference"
        " → grace passed → priority 3"
    )


def test_step_render_variants() -> None:
    assert render_step(ProfileMatched(profile_name="global defaults", layer="global"))
    assert (
        render_step(TargetMissing(language="da", forced=True, hi=True))
        == "missing `da` (forced) (hi)"
    )
    assert render_step(SourceElected(chosen="en")) == "source `en`"
    assert (
        render_step(SourceElected(chosen="en", considered=("ja", "de")))
        == "source `en` over `ja`, `de` by preference"
    )
    assert (
        render_step(GraceEvaluated(passed=False, age_hours=36, threshold_hours=168))
        == "grace pending (36h of 168h)"
    )
    assert render_step(GraceEvaluated(passed=False)) == "grace pending"
    assert (
        render_step(SkipEvaluated(skipped=True, condition="unmonitored"))
        == "skipped: unmonitored"
    )
    assert render_step(SkipEvaluated(skipped=False)) == "no skip condition"
    assert (
        render_step(ExclusionMatched(kind="tag", rule_key="no-translate"))
        == "excluded by tag rule `no-translate`"
    )
    assert (
        render_step(Withdrawn(reason="no longer wanted"))
        == "withdrawn: no longer wanted"
    )
    assert (
        render_step(EvidenceObserved(kind="bazarr_history", detail="action 6 at 14:02"))
        == "bazarr history: action 6 at 14:02"
    )
    assert render_step(Dispatched()) == "dispatched"
    assert render_step(Dispatched(note="slot 1 of 2")) == "dispatched (slot 1 of 2)"
    assert (
        render_step(BlockedByRail(rail="cap", detail="daily cap 200/200"))
        == "blocked: daily cap 200/200"
    )


def test_encode_decode_round_trip() -> None:
    steps: list[TraceStep] = [
        ProfileMatched(profile_name="Anime", layer="profile"),
        TargetMissing(language="da", forced=True),
        SourceElected(chosen="en", considered=("ja",)),
        GraceEvaluated(passed=False, age_hours=1, threshold_hours=48),
        PriorityAssigned(score=7, components={"recency": 5, "monitored": 2}),
        BlockedByRail(rail="invariant", detail="series pair already in flight"),
    ]
    encoded = encode_trace(steps)
    assert all("type" in record for record in encoded)  # tag field persisted
    assert decode_trace(encoded) == tuple(steps)


def test_decode_tolerates_foreign_vocabulary() -> None:
    assert decode_trace(None) == ()
    assert decode_trace([{"type": "from_a_future_build", "x": 1}]) == ()


def test_decode_drops_only_unknown_steps_from_mixed_payload() -> None:
    # A future build may append steps this build doesn't know: the known
    # prefix/suffix must survive, only the foreign step is dropped.
    mixed: list[dict[str, object]] = [
        {"type": "target_missing", "language": "da"},
        {"type": "from_a_future_build", "x": 1},
        {"type": "withdrawn", "reason": "no longer wanted"},
    ]
    assert decode_trace(mixed) == (
        TargetMissing(language="da"),
        Withdrawn(reason="no longer wanted"),
    )
