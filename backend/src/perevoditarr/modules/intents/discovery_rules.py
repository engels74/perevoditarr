"""Discovery decision rules (P2-T3, FR-P1): pure domain logic.

`explain_candidate` runs one wanted subtitle through the effective policy —
target match, HI/forced target rules, skip conditions, exclusions, source
election per preference order, grace — and returns a tagged decision carrying
the full trace. Discovery upserts only `Planned` outcomes into the ledger;
the same function powers the "why is this not planned?" explainer (P2-T5/T6),
so planned and not-planned items are explained by the identical rule chain.

Deliberately imports nothing from sqlalchemy/litestar/httpx: the discovery
service converts mirror rows into these plain structs before calling in.
"""

from datetime import datetime
from typing import Literal

import msgspec

from perevoditarr.modules.intents.trace import (
    ExclusionMatched,
    GraceEvaluated,
    ProfileMatched,
    SkipEvaluated,
    SourceElected,
    TargetMissing,
    TraceStep,
)
from perevoditarr.modules.policy import (
    EffectivePolicy,
    EpisodeRef,
    ExclusionRule,
    LanguagePair,
    LanguagePairExclusion,
    MovieExclusion,
    MovieRef,
    SeriesExclusion,
    TagExclusion,
    match_exclusions,
)


class ExistingSubtitle(msgspec.Struct, kw_only=True, frozen=True):
    """One existing subtitle as the mirror reports it (file or embedded)."""

    language: str  # Bazarr code2
    forced: bool = False
    hi: bool = False
    embedded: bool = False  # mirror file_path is None ⇒ embedded track


class WantedCandidate(msgspec.Struct, kw_only=True, frozen=True):
    """One wanted subtitle joined with its item context — plain data."""

    item: EpisodeRef | MovieRef
    # Show title for episodes, movie title for movies (§6.5 granularity).
    display_title: str
    language: str  # wanted target (code2)
    forced: bool = False
    hi: bool = False
    season: int | None = None
    episode_number: int | None = None
    # When the want first appeared in our mirror — the universally available
    # recency anchor. Bazarr's episodes/movies APIs expose no airing/import
    # date (verified against the v1.5.6 source), so `air_date` stays None
    # today; it is preferred automatically if a future version supplies it.
    wanted_first_seen_at: datetime
    air_date: datetime | None = None
    # Continuing-vs-ended scorer input (FR-Q4); None for movies/unknown.
    series_ended: bool | None = None
    existing_subtitles: tuple[ExistingSubtitle, ...] = ()


def recency_anchor(candidate: WantedCandidate) -> datetime:
    """The one recency signal shared by grace evaluation and the scorer."""
    return candidate.air_date or candidate.wanted_first_seen_at


type NotPlannedReason = Literal[
    "target_not_in_policy",
    "hi_target_disabled",
    "forced_target_disabled",
    "unmonitored",
    "excluded",
    "embedded_target_exists",
    "no_eligible_source",
    "grace_pending",
]


class Planned(msgspec.Struct, kw_only=True, frozen=True, tag="planned"):
    source_language: str
    trace: tuple[TraceStep, ...]


class NotPlanned(msgspec.Struct, kw_only=True, frozen=True, tag="not_planned"):
    reason: NotPlannedReason
    detail: str
    trace: tuple[TraceStep, ...]


type CandidateDecision = Planned | NotPlanned


def _exclusion_key(rule: ExclusionRule) -> tuple[str, str]:
    match rule:
        case SeriesExclusion(sonarr_series_id=series_id):
            return "series", str(series_id)
        case MovieExclusion(radarr_id=radarr_id):
            return "movie", str(radarr_id)
        case TagExclusion(tag_value=tag):
            return "tag", tag
        case LanguagePairExclusion(source_language=source, target_language=target):
            return "language_pair", f"{source}->{target}"


def _exclusion_steps(rules: tuple[ExclusionRule, ...]) -> tuple[TraceStep, ...]:
    return tuple(
        ExclusionMatched(kind=kind, rule_key=key)
        for kind, key in (_exclusion_key(rule) for rule in rules)
    )


def _elect_source(
    candidate: WantedCandidate, policy: EffectivePolicy
) -> tuple[str | None, tuple[str, ...]]:
    """First preference with an eligible existing subtitle wins.

    Eligible: file-backed (embedded tracks have no path for Bazarr's translate
    PATCH to read), not the target language itself, and HI/forced variants
    only when the policy allows them as sources.
    """
    passed_over: list[str] = []
    for preference in policy.source_preferences.value:
        if preference == candidate.language:
            continue  # translating a language into itself is never eligible
        eligible = [
            subtitle
            for subtitle in candidate.existing_subtitles
            if subtitle.language == preference
            and not subtitle.embedded
            and (policy.allow_hi_source.value or not subtitle.hi)
            and (policy.allow_forced_source.value or not subtitle.forced)
        ]
        if eligible:
            return preference, tuple(passed_over)
        passed_over.append(preference)
    return None, tuple(passed_over)


def _grace(
    candidate: WantedCandidate, policy: EffectivePolicy, now: datetime
) -> GraceEvaluated:
    threshold = (
        policy.grace_hours_episodes.value
        if isinstance(candidate.item, EpisodeRef)
        else policy.grace_hours_movies.value
    )
    # Same anchor the scorer uses — grace and recency must never diverge.
    anchor = recency_anchor(candidate)
    age_hours = max(0, int((now - anchor).total_seconds() // 3600))
    return GraceEvaluated(
        passed=age_hours >= threshold, age_hours=age_hours, threshold_hours=threshold
    )


def explain_candidate(
    candidate: WantedCandidate,
    policy: EffectivePolicy,
    exclusions: tuple[ExclusionRule, ...],
    *,
    now: datetime,
) -> CandidateDecision:
    provenance = policy.target_languages.provenance
    trace: list[TraceStep] = [
        ProfileMatched(
            profile_name=provenance.source_name or "global defaults",
            layer=provenance.layer,
        )
    ]

    if candidate.language not in policy.target_languages.value:
        detail = f"target `{candidate.language}` not in policy targets"
        trace.append(SkipEvaluated(skipped=True, condition=detail))
        return NotPlanned(
            reason="target_not_in_policy", detail=detail, trace=tuple(trace)
        )
    trace.append(
        TargetMissing(
            language=candidate.language, forced=candidate.forced, hi=candidate.hi
        )
    )

    if candidate.hi and not policy.translate_hi_targets.value:
        detail = "HI targets disabled by policy"
        trace.append(SkipEvaluated(skipped=True, condition=detail))
        return NotPlanned(
            reason="hi_target_disabled", detail=detail, trace=tuple(trace)
        )
    if candidate.forced and not policy.translate_forced_targets.value:
        detail = "forced targets disabled by policy"
        trace.append(SkipEvaluated(skipped=True, condition=detail))
        return NotPlanned(
            reason="forced_target_disabled", detail=detail, trace=tuple(trace)
        )

    if policy.skip_unmonitored.value and not candidate.item.monitored:
        detail = "unmonitored"
        trace.append(SkipEvaluated(skipped=True, condition=detail))
        return NotPlanned(reason="unmonitored", detail=detail, trace=tuple(trace))

    item_rules = match_exclusions(candidate.item, exclusions, pair=None)
    if item_rules:
        trace.extend(_exclusion_steps(item_rules))
        return NotPlanned(
            reason="excluded",
            detail="matched exclusion rule",
            trace=tuple(trace),
        )

    if policy.skip_if_embedded_target.value and any(
        subtitle.embedded
        and subtitle.language == candidate.language
        and subtitle.forced == candidate.forced
        and subtitle.hi == candidate.hi
        for subtitle in candidate.existing_subtitles
    ):
        detail = "embedded target track exists"
        trace.append(SkipEvaluated(skipped=True, condition=detail))
        return NotPlanned(
            reason="embedded_target_exists", detail=detail, trace=tuple(trace)
        )

    chosen, passed_over = _elect_source(candidate, policy)
    if chosen is None:
        preferences = ", ".join(f"`{code}`" for code in policy.source_preferences.value)
        detail = f"no eligible source among {preferences or 'no preferences'}"
        trace.append(SkipEvaluated(skipped=True, condition=detail))
        return NotPlanned(
            reason="no_eligible_source", detail=detail, trace=tuple(trace)
        )
    trace.append(SourceElected(chosen=chosen, considered=passed_over))

    # Item-level rules were handled above; only pair rules can match here.
    pair_rules = match_exclusions(
        candidate.item,
        exclusions,
        pair=LanguagePair(source=chosen, target=candidate.language),
    )
    pair_only = tuple(
        rule for rule in pair_rules if isinstance(rule, LanguagePairExclusion)
    )
    if pair_only:
        trace.extend(_exclusion_steps(pair_only))
        return NotPlanned(
            reason="excluded",
            detail=f"language pair `{chosen}->{candidate.language}` excluded",
            trace=tuple(trace),
        )

    grace = _grace(candidate, policy, now)
    trace.append(grace)
    if not grace.passed:
        return NotPlanned(
            reason="grace_pending",
            detail=f"grace pending ({grace.age_hours}h of {grace.threshold_hours}h)",
            trace=tuple(trace),
        )

    return Planned(source_language=chosen, trace=tuple(trace))
