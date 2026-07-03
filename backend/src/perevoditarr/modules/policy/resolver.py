"""Cascade resolver (P2-T1, PRD §8.1): pure domain logic, zero I/O imports.

`resolve_effective_policy(item, cascade)` folds the layer chain
global defaults → active preset → assigned profile (most specific scope wins)
→ per-item override, stamping every effective value with its provenance
(layer + source id). This module is the single source of truth for effective
policy — discovery, dispatch, UI, and doctor all consume it; none re-derive.

Deliberately imports nothing from sqlalchemy/litestar/httpx: the service layer
converts ORM rows into these plain structs before calling in.
"""

from typing import Literal
from uuid import UUID

import msgspec

type LayerName = Literal["global", "preset", "profile", "override"]

# §6.3: Bazarr converts these code2 values before calling Lingarr. Exported so
# validation and the doctor single-source the table.
CODE2_CONVERSIONS: dict[str, str] = {"zh": "zh-CN", "zt": "zh-TW", "pb": "pt-BR"}


class PriorityWeights(msgspec.Struct, kw_only=True, frozen=True):
    """Scorer weights (FR-Q4, P2-T5). Cascades as one atomic value: a layer
    that sets `priority_weights` supplies the whole set (unset fields take
    these defaults, not the parent layer's values) — per-field provenance
    would multiply UI chips without adding real control."""

    episode_base: int = 10
    movie_base: int = 10
    monitored_bonus: int = 20
    continuing_bonus: int = 15
    # Recency decays exponentially from the anchor (air date when known,
    # else first-seen): full weight when brand new, half after each half-life.
    recency_max: int = 40
    recency_half_life_hours: int = 168
    # Watch-aware bonuses (P5-T1, FR-Q5): applied only when a configured watch
    # source reports activity for the item (ADR-0007). Cascade as part of the
    # same atomic weight set; a fresh install with no watch source never boosts.
    watch_recent_bonus: int = 15
    watch_frequent_bonus: int = 10
    watchlist_bonus: int = 10


class PolicyValues(msgspec.Struct, kw_only=True, omit_defaults=True):
    """One layer's contribution: None means 'not set here — inherit'."""

    dry_run: bool | None = None
    target_languages: list[str] | None = None
    source_preferences: list[str] | None = None
    allow_hi_source: bool | None = None
    allow_forced_source: bool | None = None
    translate_hi_targets: bool | None = None
    translate_forced_targets: bool | None = None
    grace_hours_episodes: int | None = None
    grace_hours_movies: int | None = None
    skip_if_embedded_target: bool | None = None
    skip_unmonitored: bool | None = None
    priority_weights: PriorityWeights | None = None


class Provenance(msgspec.Struct, kw_only=True, frozen=True):
    layer: LayerName
    source_id: UUID | None = None
    source_name: str | None = None


class Resolved[T](msgspec.Struct, kw_only=True, frozen=True):
    value: T
    provenance: Provenance


class EffectivePolicy(msgspec.Struct, kw_only=True, frozen=True):
    dry_run: Resolved[bool]
    target_languages: Resolved[tuple[str, ...]]
    source_preferences: Resolved[tuple[str, ...]]
    allow_hi_source: Resolved[bool]
    allow_forced_source: Resolved[bool]
    translate_hi_targets: Resolved[bool]
    translate_forced_targets: Resolved[bool]
    grace_hours_episodes: Resolved[int]
    grace_hours_movies: Resolved[int]
    skip_if_embedded_target: Resolved[bool]
    skip_unmonitored: Resolved[bool]
    priority_weights: Resolved[PriorityWeights]


# Safe-by-default (PRD G4): a fresh install with no preset dispatches nothing
# and wants nothing until targets are configured.
GLOBAL_DEFAULTS = PolicyValues(
    dry_run=True,
    target_languages=[],
    source_preferences=["en"],
    allow_hi_source=True,
    allow_forced_source=False,
    translate_hi_targets=False,
    translate_forced_targets=False,
    grace_hours_episodes=72,
    grace_hours_movies=168,
    skip_if_embedded_target=False,
    skip_unmonitored=True,
    priority_weights=PriorityWeights(),
)


# --- items ------------------------------------------------------------------


class SeriesRef(msgspec.Struct, kw_only=True, frozen=True, tag="series"):
    bazarr_instance_id: UUID
    sonarr_series_id: int
    tags: tuple[str, ...] = ()
    monitored: bool = True


class EpisodeRef(msgspec.Struct, kw_only=True, frozen=True, tag="episode"):
    bazarr_instance_id: UUID
    sonarr_series_id: int
    sonarr_episode_id: int
    tags: tuple[str, ...] = ()
    monitored: bool = True


class MovieRef(msgspec.Struct, kw_only=True, frozen=True, tag="movie"):
    bazarr_instance_id: UUID
    radarr_id: int
    tags: tuple[str, ...] = ()
    monitored: bool = True


type ItemRef = SeriesRef | EpisodeRef | MovieRef


# --- layers -----------------------------------------------------------------


class LayerSource(msgspec.Struct, kw_only=True, frozen=True):
    """A named origin for a set of values (preset, profile, or override row)."""

    source_id: UUID | None = None
    source_name: str | None = None
    values: PolicyValues


class InstanceScope(msgspec.Struct, kw_only=True, frozen=True, tag="instance"):
    pass


class LibraryScope(msgspec.Struct, kw_only=True, frozen=True, tag="library"):
    # FR-P5: library = Sonarr/Radarr tag (root-folder grouping rides tags too).
    tag_value: str


class SeriesScope(msgspec.Struct, kw_only=True, frozen=True, tag="series"):
    sonarr_series_id: int


class MovieScope(msgspec.Struct, kw_only=True, frozen=True, tag="movie"):
    radarr_id: int


type AssignmentScope = InstanceScope | LibraryScope | SeriesScope | MovieScope


class AssignmentLayer(msgspec.Struct, kw_only=True, frozen=True):
    scope: AssignmentScope
    profile: LayerSource


class SeriesTarget(msgspec.Struct, kw_only=True, frozen=True, tag="series"):
    sonarr_series_id: int


class MovieTarget(msgspec.Struct, kw_only=True, frozen=True, tag="movie"):
    radarr_id: int


type OverrideTarget = SeriesTarget | MovieTarget


class OverrideLayer(msgspec.Struct, kw_only=True, frozen=True):
    target: OverrideTarget
    source: LayerSource


class CascadeInput(msgspec.Struct, kw_only=True, frozen=True):
    """Everything the resolver needs, already scoped to the item's instance.

    The service pre-orders assignments and overrides by ascending update time;
    among equal-specificity matches the last one wins deterministically.
    """

    preset: LayerSource | None = None
    assignments: tuple[AssignmentLayer, ...] = ()
    overrides: tuple[OverrideLayer, ...] = ()


def _scope_specificity(scope: AssignmentScope) -> int:
    match scope:
        case InstanceScope():
            return 1
        case LibraryScope():
            return 2
        case SeriesScope() | MovieScope():
            return 3


def _scope_matches(scope: AssignmentScope, item: ItemRef) -> bool:
    match scope:
        case InstanceScope():
            return True
        case LibraryScope(tag_value=tag):
            return tag in item.tags
        case SeriesScope(sonarr_series_id=series_id):
            return (
                isinstance(item, SeriesRef | EpisodeRef)
                and item.sonarr_series_id == series_id
            )
        case MovieScope(radarr_id=radarr_id):
            return isinstance(item, MovieRef) and item.radarr_id == radarr_id


def _target_matches(target: OverrideTarget, item: ItemRef) -> bool:
    match target:
        case SeriesTarget(sonarr_series_id=series_id):
            return (
                isinstance(item, SeriesRef | EpisodeRef)
                and item.sonarr_series_id == series_id
            )
        case MovieTarget(radarr_id=radarr_id):
            return isinstance(item, MovieRef) and item.radarr_id == radarr_id


def select_assignment(
    item: ItemRef, assignments: tuple[AssignmentLayer, ...]
) -> AssignmentLayer | None:
    """Most specific matching scope wins; ties resolve to the latest entry."""
    best: AssignmentLayer | None = None
    best_rank = 0
    for assignment in assignments:
        if not _scope_matches(assignment.scope, item):
            continue
        rank = _scope_specificity(assignment.scope)
        if rank >= best_rank:
            best, best_rank = assignment, rank
    return best


def select_override(
    item: ItemRef, overrides: tuple[OverrideLayer, ...]
) -> OverrideLayer | None:
    selected: OverrideLayer | None = None
    for override in overrides:
        if _target_matches(override.target, item):
            selected = override
    return selected


def _require[T](value: T | None) -> T:
    if value is None:
        # Unreachable while GLOBAL_DEFAULTS stays complete; guards field drift.
        raise TypeError("GLOBAL_DEFAULTS must set every policy field")
    return value


def _pick[T](
    current: Resolved[T], contributed: T | None, stamp: Provenance
) -> Resolved[T]:
    if contributed is None:
        return current
    return Resolved(value=contributed, provenance=stamp)


def _pick_seq(
    current: Resolved[tuple[str, ...]],
    contributed: list[str] | None,
    stamp: Provenance,
) -> Resolved[tuple[str, ...]]:
    if contributed is None:
        return current
    return Resolved(value=tuple(contributed), provenance=stamp)


def _initial() -> EffectivePolicy:
    base = Provenance(layer="global")
    defaults = GLOBAL_DEFAULTS
    return EffectivePolicy(
        dry_run=Resolved(value=_require(defaults.dry_run), provenance=base),
        target_languages=Resolved(
            value=tuple(_require(defaults.target_languages)), provenance=base
        ),
        source_preferences=Resolved(
            value=tuple(_require(defaults.source_preferences)), provenance=base
        ),
        allow_hi_source=Resolved(
            value=_require(defaults.allow_hi_source), provenance=base
        ),
        allow_forced_source=Resolved(
            value=_require(defaults.allow_forced_source), provenance=base
        ),
        translate_hi_targets=Resolved(
            value=_require(defaults.translate_hi_targets), provenance=base
        ),
        translate_forced_targets=Resolved(
            value=_require(defaults.translate_forced_targets), provenance=base
        ),
        grace_hours_episodes=Resolved(
            value=_require(defaults.grace_hours_episodes), provenance=base
        ),
        grace_hours_movies=Resolved(
            value=_require(defaults.grace_hours_movies), provenance=base
        ),
        skip_if_embedded_target=Resolved(
            value=_require(defaults.skip_if_embedded_target), provenance=base
        ),
        skip_unmonitored=Resolved(
            value=_require(defaults.skip_unmonitored), provenance=base
        ),
        priority_weights=Resolved(
            value=_require(defaults.priority_weights), provenance=base
        ),
    )


def _apply(
    effective: EffectivePolicy, layer: LayerName, source: LayerSource
) -> EffectivePolicy:
    stamp = Provenance(
        layer=layer, source_id=source.source_id, source_name=source.source_name
    )
    values = source.values
    return EffectivePolicy(
        dry_run=_pick(effective.dry_run, values.dry_run, stamp),
        target_languages=_pick_seq(
            effective.target_languages, values.target_languages, stamp
        ),
        source_preferences=_pick_seq(
            effective.source_preferences, values.source_preferences, stamp
        ),
        allow_hi_source=_pick(effective.allow_hi_source, values.allow_hi_source, stamp),
        allow_forced_source=_pick(
            effective.allow_forced_source, values.allow_forced_source, stamp
        ),
        translate_hi_targets=_pick(
            effective.translate_hi_targets, values.translate_hi_targets, stamp
        ),
        translate_forced_targets=_pick(
            effective.translate_forced_targets, values.translate_forced_targets, stamp
        ),
        grace_hours_episodes=_pick(
            effective.grace_hours_episodes, values.grace_hours_episodes, stamp
        ),
        grace_hours_movies=_pick(
            effective.grace_hours_movies, values.grace_hours_movies, stamp
        ),
        skip_if_embedded_target=_pick(
            effective.skip_if_embedded_target, values.skip_if_embedded_target, stamp
        ),
        skip_unmonitored=_pick(
            effective.skip_unmonitored, values.skip_unmonitored, stamp
        ),
        priority_weights=_pick(
            effective.priority_weights, values.priority_weights, stamp
        ),
    )


def resolve_effective_policy(item: ItemRef, cascade: CascadeInput) -> EffectivePolicy:
    effective = _initial()
    if cascade.preset is not None:
        effective = _apply(effective, "preset", cascade.preset)
    if (assignment := select_assignment(item, cascade.assignments)) is not None:
        effective = _apply(effective, "profile", assignment.profile)
    if (override := select_override(item, cascade.overrides)) is not None:
        effective = _apply(effective, "override", override.source)
    return effective


# --- exclusions (FR-P3) -------------------------------------------------------


class LanguagePair(msgspec.Struct, kw_only=True, frozen=True):
    source: str
    target: str


class SeriesExclusion(msgspec.Struct, kw_only=True, frozen=True, tag="series"):
    exclusion_id: UUID | None = None
    sonarr_series_id: int


class MovieExclusion(msgspec.Struct, kw_only=True, frozen=True, tag="movie"):
    exclusion_id: UUID | None = None
    radarr_id: int


class TagExclusion(msgspec.Struct, kw_only=True, frozen=True, tag="tag"):
    exclusion_id: UUID | None = None
    tag_value: str


class LanguagePairExclusion(
    msgspec.Struct, kw_only=True, frozen=True, tag="language_pair"
):
    exclusion_id: UUID | None = None
    source_language: str
    target_language: str


type ExclusionRule = (
    SeriesExclusion | MovieExclusion | TagExclusion | LanguagePairExclusion
)


def match_exclusions(
    item: ItemRef,
    exclusions: tuple[ExclusionRule, ...],
    pair: LanguagePair | None = None,
) -> tuple[ExclusionRule, ...]:
    """Exclusions that apply to this item (and pair, when one is given).

    Pair exclusions only match when a pair is supplied — discovery evaluates
    them per candidate pair; item-level callers pass pair=None.
    """
    matched: list[ExclusionRule] = []
    for rule in exclusions:
        match rule:
            case SeriesExclusion(sonarr_series_id=series_id):
                if (
                    isinstance(item, SeriesRef | EpisodeRef)
                    and item.sonarr_series_id == series_id
                ):
                    matched.append(rule)
            case MovieExclusion(radarr_id=radarr_id):
                if isinstance(item, MovieRef) and item.radarr_id == radarr_id:
                    matched.append(rule)
            case TagExclusion(tag_value=tag):
                if tag in item.tags:
                    matched.append(rule)
            case LanguagePairExclusion(source_language=source, target_language=target):
                if pair is not None and pair.source == source and pair.target == target:
                    matched.append(rule)
    return tuple(matched)
