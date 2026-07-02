"""Cascade resolver unit tests (P2-T1): override wins, provenance correctness,
layer-removal fallback, scope specificity, exclusion matching."""

from uuid import uuid4

import pytest

from perevoditarr.modules.policy import (
    GLOBAL_DEFAULTS,
    CascadeInput,
    EpisodeRef,
    LanguagePair,
    MovieRef,
    PolicyValues,
    match_exclusions,
    resolve_effective_policy,
)
from perevoditarr.modules.policy.resolver import (
    AssignmentLayer,
    InstanceScope,
    LanguagePairExclusion,
    LayerSource,
    LibraryScope,
    MovieExclusion,
    MovieScope,
    MovieTarget,
    OverrideLayer,
    SeriesExclusion,
    SeriesScope,
    SeriesTarget,
    TagExclusion,
)

INSTANCE = uuid4()


def episode(series_id: int = 10, tags: tuple[str, ...] = ()) -> EpisodeRef:
    return EpisodeRef(
        bazarr_instance_id=INSTANCE,
        sonarr_series_id=series_id,
        sonarr_episode_id=100,
        tags=tags,
    )


def movie(radarr_id: int = 7, tags: tuple[str, ...] = ()) -> MovieRef:
    return MovieRef(bazarr_instance_id=INSTANCE, radarr_id=radarr_id, tags=tags)


def layer(
    name: str, *, dry_run: bool | None = None, targets: list[str] | None = None
) -> LayerSource:
    return LayerSource(
        source_id=uuid4(),
        source_name=name,
        values=PolicyValues(dry_run=dry_run, target_languages=targets),
    )


def test_global_defaults_apply_with_global_provenance() -> None:
    effective = resolve_effective_policy(episode(), CascadeInput())
    assert effective.dry_run.value is True
    assert effective.dry_run.provenance.layer == "global"
    assert effective.target_languages.value == ()
    assert effective.grace_hours_episodes.value == GLOBAL_DEFAULTS.grace_hours_episodes


def test_each_layer_overrides_the_previous_with_provenance() -> None:
    preset = layer("Balanced", dry_run=False, targets=["da"])
    profile = layer("Anime", targets=["da", "sv"])
    override = LayerSource(
        source_id=uuid4(),
        source_name="series override",
        values=PolicyValues(target_languages=["nb"]),
    )
    cascade = CascadeInput(
        preset=preset,
        assignments=(AssignmentLayer(scope=InstanceScope(), profile=profile),),
        overrides=(
            OverrideLayer(target=SeriesTarget(sonarr_series_id=10), source=override),
        ),
    )
    effective = resolve_effective_policy(episode(), cascade)
    # dry_run: only the preset sets it.
    assert effective.dry_run.value is False
    assert effective.dry_run.provenance.layer == "preset"
    assert effective.dry_run.provenance.source_name == "Balanced"
    # target_languages: override wins over profile over preset.
    assert effective.target_languages.value == ("nb",)
    assert effective.target_languages.provenance.layer == "override"
    # untouched fields keep global provenance.
    assert effective.skip_unmonitored.provenance.layer == "global"


def test_layer_removal_falls_back_to_the_next_layer() -> None:
    preset = layer("Balanced", targets=["da"])
    profile = layer("Anime", targets=["sv"])
    override = OverrideLayer(
        target=SeriesTarget(sonarr_series_id=10),
        source=LayerSource(
            source_id=uuid4(),
            source_name="series override",
            values=PolicyValues(target_languages=["nb"]),
        ),
    )
    assignment = AssignmentLayer(scope=InstanceScope(), profile=profile)

    with_all = resolve_effective_policy(
        episode(),
        CascadeInput(preset=preset, assignments=(assignment,), overrides=(override,)),
    )
    assert with_all.target_languages.value == ("nb",)

    without_override = resolve_effective_policy(
        episode(), CascadeInput(preset=preset, assignments=(assignment,))
    )
    assert without_override.target_languages.value == ("sv",)
    assert without_override.target_languages.provenance.layer == "profile"

    without_profile = resolve_effective_policy(episode(), CascadeInput(preset=preset))
    assert without_profile.target_languages.value == ("da",)
    assert without_profile.target_languages.provenance.layer == "preset"

    bare = resolve_effective_policy(episode(), CascadeInput())
    assert bare.target_languages.value == ()
    assert bare.target_languages.provenance.layer == "global"


@pytest.mark.parametrize(
    ("item", "expected_profile"),
    [
        (episode(series_id=10), "series-profile"),
        (episode(series_id=99, tags=("anime",)), "library-profile"),
        (episode(series_id=99), "instance-profile"),
        (movie(radarr_id=7), "movie-profile"),
    ],
)
def test_most_specific_assignment_scope_wins(
    item: EpisodeRef | MovieRef, expected_profile: str
) -> None:
    assignments = (
        AssignmentLayer(
            scope=InstanceScope(), profile=layer("instance-profile", targets=["en"])
        ),
        AssignmentLayer(
            scope=LibraryScope(tag_value="anime"),
            profile=layer("library-profile", targets=["da"]),
        ),
        AssignmentLayer(
            scope=SeriesScope(sonarr_series_id=10),
            profile=layer("series-profile", targets=["sv"]),
        ),
        AssignmentLayer(
            scope=MovieScope(radarr_id=7),
            profile=layer("movie-profile", targets=["nb"]),
        ),
    )
    effective = resolve_effective_policy(item, CascadeInput(assignments=assignments))
    assert effective.target_languages.provenance.source_name == expected_profile


def test_equal_specificity_ties_resolve_to_latest_assignment() -> None:
    first = AssignmentLayer(
        scope=InstanceScope(), profile=layer("first", targets=["da"])
    )
    second = AssignmentLayer(
        scope=InstanceScope(), profile=layer("second", targets=["sv"])
    )
    effective = resolve_effective_policy(
        episode(), CascadeInput(assignments=(first, second))
    )
    assert effective.target_languages.provenance.source_name == "second"


def test_series_override_does_not_apply_to_movies() -> None:
    override = OverrideLayer(
        target=SeriesTarget(sonarr_series_id=7),
        source=LayerSource(
            source_id=uuid4(),
            source_name="series override",
            values=PolicyValues(dry_run=False),
        ),
    )
    effective = resolve_effective_policy(
        movie(radarr_id=7), CascadeInput(overrides=(override,))
    )
    assert effective.dry_run.value is True  # global default, untouched


def test_movie_override_applies_by_radarr_id() -> None:
    override = OverrideLayer(
        target=MovieTarget(radarr_id=7),
        source=LayerSource(
            source_id=uuid4(),
            source_name="movie override",
            values=PolicyValues(dry_run=False),
        ),
    )
    effective = resolve_effective_policy(
        movie(radarr_id=7), CascadeInput(overrides=(override,))
    )
    assert effective.dry_run.value is False
    assert effective.dry_run.provenance.layer == "override"


def test_none_valued_override_field_inherits_from_lower_layers() -> None:
    preset = layer("Balanced", dry_run=False)
    override = OverrideLayer(
        target=SeriesTarget(sonarr_series_id=10),
        source=LayerSource(
            source_id=uuid4(),
            source_name="series override",
            values=PolicyValues(target_languages=["nb"]),  # dry_run unset
        ),
    )
    effective = resolve_effective_policy(
        episode(), CascadeInput(preset=preset, overrides=(override,))
    )
    assert effective.dry_run.value is False
    assert effective.dry_run.provenance.layer == "preset"


# --- exclusions --------------------------------------------------------------


def test_series_and_tag_exclusions_match_episodes() -> None:
    rules = (
        SeriesExclusion(sonarr_series_id=10),
        TagExclusion(tag_value="anime"),
        MovieExclusion(radarr_id=7),
    )
    matched = match_exclusions(episode(series_id=10, tags=("anime",)), rules)
    assert {type(rule) for rule in matched} == {SeriesExclusion, TagExclusion}


def test_language_pair_exclusion_requires_a_pair() -> None:
    rules = (LanguagePairExclusion(source_language="en", target_language="da"),)
    assert match_exclusions(episode(), rules) == ()
    assert (
        match_exclusions(episode(), rules, pair=LanguagePair(source="en", target="da"))
        == rules
    )
    assert (
        match_exclusions(episode(), rules, pair=LanguagePair(source="en", target="sv"))
        == ()
    )


def test_movie_exclusion_matches_only_that_movie() -> None:
    rules = (MovieExclusion(radarr_id=7),)
    assert match_exclusions(movie(radarr_id=7), rules) == rules
    assert match_exclusions(movie(radarr_id=8), rules) == ()
    assert match_exclusions(episode(), rules) == ()
