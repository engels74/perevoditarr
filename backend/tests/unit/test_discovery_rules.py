"""Discovery rule layer (P2-T3): language matching incl. code2 edge cases,
HI/forced permutations, grace boundaries, and exclusion layers — pure, no DB."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from perevoditarr.modules.intents.discovery_rules import (
    CandidateDecision,
    ExistingSubtitle,
    NotPlanned,
    Planned,
    WantedCandidate,
    explain_candidate,
)
from perevoditarr.modules.intents.trace import render_human
from perevoditarr.modules.policy import (
    CascadeInput,
    EffectivePolicy,
    EpisodeRef,
    ExclusionRule,
    LanguagePairExclusion,
    MovieRef,
    PolicyValues,
    SeriesExclusion,
    TagExclusion,
    resolve_effective_policy,
)
from perevoditarr.modules.policy.resolver import LayerSource

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
INSTANCE_ID = UUID("00000000-0000-0000-0000-000000000001")

EN = ExistingSubtitle(language="en")
DE = ExistingSubtitle(language="de")


def _values(**overrides: object) -> PolicyValues:
    base = PolicyValues(
        target_languages=["da"],
        source_preferences=["en", "de"],
        grace_hours_episodes=72,
        grace_hours_movies=168,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _policy(
    item: EpisodeRef | MovieRef, values: PolicyValues | None = None
) -> EffectivePolicy:
    preset = LayerSource(
        source_id=uuid4(), source_name="Test", values=values or _values()
    )
    return resolve_effective_policy(item, CascadeInput(preset=preset))


def _episode(
    *,
    tags: tuple[str, ...] = (),
    monitored: bool = True,
    language: str = "da",
    forced: bool = False,
    hi: bool = False,
    first_seen_hours_ago: float = 100.0,
    air_date: datetime | None = None,
    subtitles: tuple[ExistingSubtitle, ...] = (EN,),
) -> WantedCandidate:
    return WantedCandidate(
        item=EpisodeRef(
            bazarr_instance_id=INSTANCE_ID,
            sonarr_series_id=11,
            sonarr_episode_id=101,
            tags=tags,
            monitored=monitored,
        ),
        display_title="Alpha Show",
        language=language,
        forced=forced,
        hi=hi,
        season=1,
        episode_number=1,
        wanted_first_seen_at=NOW - timedelta(hours=first_seen_hours_ago),
        air_date=air_date,
        existing_subtitles=subtitles,
    )


def _movie(
    *,
    first_seen_hours_ago: float = 400.0,
    subtitles: tuple[ExistingSubtitle, ...] = (EN,),
) -> WantedCandidate:
    return WantedCandidate(
        item=MovieRef(bazarr_instance_id=INSTANCE_ID, radarr_id=7, monitored=True),
        display_title="Alpha Movie",
        language="da",
        wanted_first_seen_at=NOW - timedelta(hours=first_seen_hours_ago),
        existing_subtitles=subtitles,
    )


def _explain(
    candidate: WantedCandidate,
    values: PolicyValues | None = None,
    exclusions: tuple[ExclusionRule, ...] = (),
) -> CandidateDecision:
    return explain_candidate(
        candidate, _policy(candidate.item, values), exclusions, now=NOW
    )


def test_happy_path_plans_and_renders_the_prd_trace_shape() -> None:
    decision = _explain(_episode())
    assert isinstance(decision, Planned)
    assert decision.source_language == "en"
    rendered = render_human(decision.trace)
    assert "profile *Test*" in rendered
    assert "missing `da`" in rendered
    assert "source `en`" in rendered
    assert "grace passed" in rendered


# --- language matching (FR-P4, code2 space) ---------------------------------


@pytest.mark.parametrize(
    ("targets", "wanted", "planned"),
    [
        (["da"], "da", True),
        (["da"], "fr", False),
        # Exact Bazarr code2 space: converted forms never match raw wants.
        (["pb"], "pb", True),
        (["pt-BR"], "pb", False),
        (["zh"], "zh", True),
        (["zh-CN"], "zh", False),
        (["zt"], "zt", True),
        (["zh-TW"], "zt", False),
    ],
)
def test_target_matching_is_exact_code2(
    targets: list[str], wanted: str, planned: bool
) -> None:
    decision = _explain(_episode(language=wanted), _values(target_languages=targets))
    if planned:
        assert isinstance(decision, Planned)
    else:
        assert isinstance(decision, NotPlanned)
        assert decision.reason == "target_not_in_policy"


# --- HI/forced permutations ---------------------------------------------------


@pytest.mark.parametrize(
    ("hi", "forced", "allow_hi", "allow_forced", "expected"),
    [
        (False, False, False, False, "planned"),
        (True, False, False, False, "hi_target_disabled"),
        (True, False, True, False, "planned"),
        (False, True, False, False, "forced_target_disabled"),
        (False, True, False, True, "planned"),
    ],
)
def test_hi_forced_target_rules(
    hi: bool, forced: bool, allow_hi: bool, allow_forced: bool, expected: str
) -> None:
    decision = _explain(
        _episode(hi=hi, forced=forced),
        _values(translate_hi_targets=allow_hi, translate_forced_targets=allow_forced),
    )
    if expected == "planned":
        assert isinstance(decision, Planned)
    else:
        assert isinstance(decision, NotPlanned)
        assert decision.reason == expected


def test_hi_source_excluded_when_not_allowed() -> None:
    hi_en = ExistingSubtitle(language="en", hi=True)
    decision = _explain(_episode(subtitles=(hi_en, DE)), _values(allow_hi_source=False))
    assert isinstance(decision, Planned)
    assert decision.source_language == "de"


def test_forced_source_excluded_by_default() -> None:
    forced_en = ExistingSubtitle(language="en", forced=True)
    decision = _explain(_episode(subtitles=(forced_en,)))
    assert isinstance(decision, NotPlanned)
    assert decision.reason == "no_eligible_source"


# --- source election ----------------------------------------------------------


def test_preference_order_elects_first_available() -> None:
    decision = _explain(_episode(subtitles=(EN, DE)))
    assert isinstance(decision, Planned)
    assert decision.source_language == "en"


def test_missing_preferred_source_falls_through_and_is_recorded() -> None:
    decision = _explain(_episode(subtitles=(DE,)))
    assert isinstance(decision, Planned)
    assert decision.source_language == "de"
    assert "source `de` over `en` by preference" in render_human(decision.trace)


def test_embedded_source_is_not_eligible() -> None:
    embedded_en = ExistingSubtitle(language="en", embedded=True)
    decision = _explain(_episode(subtitles=(embedded_en, DE)))
    assert isinstance(decision, Planned)
    assert decision.source_language == "de"


def test_source_never_equals_target() -> None:
    da = ExistingSubtitle(language="da")
    decision = _explain(
        _episode(language="da", subtitles=(da, EN)),
        _values(source_preferences=["da", "en"]),
    )
    assert isinstance(decision, Planned)
    assert decision.source_language == "en"


def test_no_source_at_all() -> None:
    decision = _explain(_episode(subtitles=()))
    assert isinstance(decision, NotPlanned)
    assert decision.reason == "no_eligible_source"


# --- grace boundaries ----------------------------------------------------------


@pytest.mark.parametrize(
    ("hours_ago", "planned"),
    [(72.0, True), (71.5, False), (200.0, True), (0.0, False)],
)
def test_episode_grace_boundary(hours_ago: float, planned: bool) -> None:
    decision = _explain(_episode(first_seen_hours_ago=hours_ago))
    if planned:
        assert isinstance(decision, Planned)
    else:
        assert isinstance(decision, NotPlanned)
        assert decision.reason == "grace_pending"


@pytest.mark.parametrize(("hours_ago", "planned"), [(168.0, True), (167.0, False)])
def test_movie_grace_uses_movie_threshold(hours_ago: float, planned: bool) -> None:
    decision = _explain(_movie(first_seen_hours_ago=hours_ago))
    if planned:
        assert isinstance(decision, Planned)
    else:
        assert isinstance(decision, NotPlanned)
        assert decision.reason == "grace_pending"


def test_air_date_preferred_over_first_seen_for_episodes() -> None:
    decision = _explain(
        _episode(first_seen_hours_ago=1.0, air_date=NOW - timedelta(hours=200))
    )
    assert isinstance(decision, Planned)


# --- skip conditions & exclusions ----------------------------------------------


def test_unmonitored_skipped_by_default_and_translatable_when_disabled() -> None:
    skipped = _explain(_episode(monitored=False))
    assert isinstance(skipped, NotPlanned)
    assert skipped.reason == "unmonitored"
    planned = _explain(_episode(monitored=False), _values(skip_unmonitored=False))
    assert isinstance(planned, Planned)


def test_embedded_target_skip_condition() -> None:
    embedded_da = ExistingSubtitle(language="da", embedded=True)
    skipped = _explain(
        _episode(subtitles=(EN, embedded_da)),
        _values(skip_if_embedded_target=True),
    )
    assert isinstance(skipped, NotPlanned)
    assert skipped.reason == "embedded_target_exists"
    # Flag mismatch (forced embedded vs plain want) does not skip.
    embedded_forced = ExistingSubtitle(language="da", embedded=True, forced=True)
    planned = _explain(
        _episode(subtitles=(EN, embedded_forced)),
        _values(skip_if_embedded_target=True),
    )
    assert isinstance(planned, Planned)


def test_series_exclusion_blocks_its_episodes() -> None:
    decision = _explain(_episode(), exclusions=(SeriesExclusion(sonarr_series_id=11),))
    assert isinstance(decision, NotPlanned)
    assert decision.reason == "excluded"
    assert "excluded by series rule `11`" in render_human(decision.trace)


def test_tag_exclusion_matches_item_tags() -> None:
    decision = _explain(
        _episode(tags=("anime",)), exclusions=(TagExclusion(tag_value="anime"),)
    )
    assert isinstance(decision, NotPlanned)
    assert decision.reason == "excluded"
    other = _explain(_episode(), exclusions=(TagExclusion(tag_value="anime"),))
    assert isinstance(other, Planned)


def test_language_pair_exclusion_blocks_only_the_elected_pair() -> None:
    blocked = _explain(
        _episode(),
        exclusions=(LanguagePairExclusion(source_language="en", target_language="da"),),
    )
    assert isinstance(blocked, NotPlanned)
    assert blocked.reason == "excluded"
    unrelated = _explain(
        _episode(),
        exclusions=(LanguagePairExclusion(source_language="de", target_language="da"),),
    )
    assert isinstance(unrelated, Planned)
