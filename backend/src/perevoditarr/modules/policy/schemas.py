"""Policy API DTOs (P2-T1). camelCase on the wire via ApiStruct/ApiRequest.

`PolicyValuesDto` mirrors `resolver.PolicyValues` field-for-field; the
converters below are the only bridge between wire shape and domain shape so
the resolver stays transport-free.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import msgspec
from msgspec import UNSET, UnsetType

from perevoditarr.core.schemas import ApiRequest, ApiStruct
from perevoditarr.modules.policy.resolver import (
    EffectivePolicy,
    PolicyValues,
    PriorityWeights,
    Provenance,
    Resolved,
)
from perevoditarr.modules.policy.validation import PolicyFinding, ValidationSeverity

LanguageCode = Annotated[
    str,
    msgspec.Meta(
        min_length=2, max_length=8, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z]{2,4})?$"
    ),
]
PolicyName = Annotated[str, msgspec.Meta(min_length=1, max_length=64)]
GraceHours = Annotated[int, msgspec.Meta(ge=0, le=24 * 365)]

type ScopeType = Literal["instance", "library", "series", "movie"]
type ExclusionKind = Literal["series", "movie", "tag", "language_pair"]
type MediaType = Literal["series", "movie"]

EXPORT_SCHEMA_VERSION = 1

ScoreWeight = Annotated[int, msgspec.Meta(ge=0, le=1000)]
HalfLifeHours = Annotated[int, msgspec.Meta(ge=1, le=24 * 365)]


class PriorityWeightsDto(ApiStruct, omit_defaults=True):
    episode_base: ScoreWeight = 10
    movie_base: ScoreWeight = 10
    monitored_bonus: ScoreWeight = 20
    continuing_bonus: ScoreWeight = 15
    recency_max: ScoreWeight = 40
    recency_half_life_hours: HalfLifeHours = 168


class PriorityWeightsRequest(ApiRequest):
    episode_base: ScoreWeight = 10
    movie_base: ScoreWeight = 10
    monitored_bonus: ScoreWeight = 20
    continuing_bonus: ScoreWeight = 15
    recency_max: ScoreWeight = 40
    recency_half_life_hours: HalfLifeHours = 168


class PolicyValuesDto(ApiStruct, omit_defaults=True):
    dry_run: bool | None = None
    target_languages: list[LanguageCode] | None = None
    source_preferences: list[LanguageCode] | None = None
    allow_hi_source: bool | None = None
    allow_forced_source: bool | None = None
    translate_hi_targets: bool | None = None
    translate_forced_targets: bool | None = None
    grace_hours_episodes: GraceHours | None = None
    grace_hours_movies: GraceHours | None = None
    skip_if_embedded_target: bool | None = None
    skip_unmonitored: bool | None = None
    priority_weights: PriorityWeightsDto | None = None


class PolicyValuesRequest(ApiRequest):
    dry_run: bool | None = None
    target_languages: (
        Annotated[list[LanguageCode], msgspec.Meta(max_length=64)] | None
    ) = None
    source_preferences: (
        Annotated[list[LanguageCode], msgspec.Meta(max_length=64)] | None
    ) = None
    allow_hi_source: bool | None = None
    allow_forced_source: bool | None = None
    translate_hi_targets: bool | None = None
    translate_forced_targets: bool | None = None
    grace_hours_episodes: GraceHours | None = None
    grace_hours_movies: GraceHours | None = None
    skip_if_embedded_target: bool | None = None
    skip_unmonitored: bool | None = None
    priority_weights: PriorityWeightsRequest | None = None


def _weights_to_domain(
    dto: PriorityWeightsDto | PriorityWeightsRequest | None,
) -> PriorityWeights | None:
    if dto is None:
        return None
    return PriorityWeights(
        episode_base=dto.episode_base,
        movie_base=dto.movie_base,
        monitored_bonus=dto.monitored_bonus,
        continuing_bonus=dto.continuing_bonus,
        recency_max=dto.recency_max,
        recency_half_life_hours=dto.recency_half_life_hours,
    )


def weights_dto(weights: PriorityWeights) -> PriorityWeightsDto:
    return PriorityWeightsDto(
        episode_base=weights.episode_base,
        movie_base=weights.movie_base,
        monitored_bonus=weights.monitored_bonus,
        continuing_bonus=weights.continuing_bonus,
        recency_max=weights.recency_max,
        recency_half_life_hours=weights.recency_half_life_hours,
    )


def to_domain_values(dto: PolicyValuesDto | PolicyValuesRequest) -> PolicyValues:
    return PolicyValues(
        dry_run=dto.dry_run,
        target_languages=dto.target_languages,
        source_preferences=dto.source_preferences,
        allow_hi_source=dto.allow_hi_source,
        allow_forced_source=dto.allow_forced_source,
        translate_hi_targets=dto.translate_hi_targets,
        translate_forced_targets=dto.translate_forced_targets,
        grace_hours_episodes=dto.grace_hours_episodes,
        grace_hours_movies=dto.grace_hours_movies,
        skip_if_embedded_target=dto.skip_if_embedded_target,
        skip_unmonitored=dto.skip_unmonitored,
        priority_weights=_weights_to_domain(dto.priority_weights),
    )


def from_domain_values(values: PolicyValues) -> PolicyValuesDto:
    return PolicyValuesDto(
        dry_run=values.dry_run,
        target_languages=values.target_languages,
        source_preferences=values.source_preferences,
        allow_hi_source=values.allow_hi_source,
        allow_forced_source=values.allow_forced_source,
        translate_hi_targets=values.translate_hi_targets,
        translate_forced_targets=values.translate_forced_targets,
        grace_hours_episodes=values.grace_hours_episodes,
        grace_hours_movies=values.grace_hours_movies,
        skip_if_embedded_target=values.skip_if_embedded_target,
        skip_unmonitored=values.skip_unmonitored,
        priority_weights=(
            weights_dto(values.priority_weights)
            if values.priority_weights is not None
            else None
        ),
    )


class RailSettingsDto(ApiStruct, omit_defaults=True):
    """Preset rail posture (§8.4) — stored now, enforced by P3-T1."""

    dispatch_window_k: Annotated[int, msgspec.Meta(ge=1, le=16)] | None = None
    hourly_cap: Annotated[int, msgspec.Meta(ge=0)] | None = None
    daily_cap: Annotated[int, msgspec.Meta(ge=0)] | None = None
    weekly_cap: Annotated[int, msgspec.Meta(ge=0)] | None = None
    budget_daily_characters: Annotated[int, msgspec.Meta(ge=0)] | None = None
    breaker_failure_threshold: Annotated[int, msgspec.Meta(ge=1)] | None = None
    breaker_probe_minutes: Annotated[int, msgspec.Meta(ge=1)] | None = None


# --- findings ----------------------------------------------------------------


class PolicyFindingRead(ApiStruct):
    code: str
    severity: ValidationSeverity
    message: str
    fix_guidance: str
    instance_name: str | None = None


def finding_read(finding: PolicyFinding) -> PolicyFindingRead:
    return PolicyFindingRead(
        code=finding.code,
        severity=finding.severity,
        message=finding.message,
        fix_guidance=finding.fix_guidance,
        instance_name=finding.instance_name,
    )


# --- presets -------------------------------------------------------------------


class PresetRead(ApiStruct):
    id: UUID
    name: str
    description: str | None
    built_in: bool
    active: bool
    values: PolicyValuesDto
    rails: RailSettingsDto
    created_at: datetime
    updated_at: datetime


class PresetCreate(ApiRequest):
    name: PolicyName
    description: str | None = None
    values: PolicyValuesRequest | None = None
    rails: RailSettingsDto | None = None


class PresetUpdate(ApiRequest):
    name: PolicyName | UnsetType = UNSET
    description: str | None | UnsetType = UNSET
    values: PolicyValuesRequest | UnsetType = UNSET
    rails: RailSettingsDto | UnsetType = UNSET


class PresetFork(ApiRequest):
    name: PolicyName


# --- profiles ------------------------------------------------------------------


class TranslationProfileRead(ApiStruct):
    id: UUID
    name: str
    description: str | None
    values: PolicyValuesDto
    assignment_count: int
    created_at: datetime
    updated_at: datetime


class ProfileEditorResponse(ApiStruct):
    """Profile plus inline validation feedback (FR-P4) for the editor."""

    profile: TranslationProfileRead
    findings: list[PolicyFindingRead]


class TranslationProfileCreate(ApiRequest):
    name: PolicyName
    description: str | None = None
    values: PolicyValuesRequest | None = None


class TranslationProfileUpdate(ApiRequest):
    name: PolicyName | UnsetType = UNSET
    description: str | None | UnsetType = UNSET
    values: PolicyValuesRequest | UnsetType = UNSET


class ProfileValidateRequest(ApiRequest):
    values: PolicyValuesRequest


class ProfileValidateResponse(ApiStruct):
    findings: list[PolicyFindingRead]


# --- assignments ---------------------------------------------------------------


class ProfileAssignmentRead(ApiStruct):
    id: UUID
    profile_id: UUID
    profile_name: str
    bazarr_instance_id: UUID
    scope_type: ScopeType
    scope_key: str
    created_at: datetime


class ProfileAssignmentCreate(ApiRequest):
    profile_id: UUID
    bazarr_instance_id: UUID
    scope_type: ScopeType
    # "" for instance scope; tag for library; arr id for series/movie.
    scope_key: Annotated[str, msgspec.Meta(max_length=128)] = ""


# --- exclusions ------------------------------------------------------------------


class ExclusionRead(ApiStruct):
    id: UUID
    bazarr_instance_id: UUID
    kind: ExclusionKind
    rule_key: str
    note: str | None
    created_at: datetime


class ExclusionCreate(ApiRequest):
    bazarr_instance_id: UUID
    kind: ExclusionKind
    rule_key: Annotated[str, msgspec.Meta(min_length=1, max_length=128)]
    note: str | None = None


# --- overrides -------------------------------------------------------------------


class OverrideRead(ApiStruct):
    id: UUID
    bazarr_instance_id: UUID
    media_type: MediaType
    media_key: str
    values: PolicyValuesDto
    created_at: datetime
    updated_at: datetime


class OverrideUpsert(ApiRequest):
    bazarr_instance_id: UUID
    media_type: MediaType
    media_key: Annotated[str, msgspec.Meta(min_length=1, max_length=32)]
    values: PolicyValuesRequest


# --- effective policy (provenance display, PRD §8.1) -----------------------------


class ProvenanceDto(ApiStruct):
    layer: Literal["global", "preset", "profile", "override"]
    source_id: UUID | None = None
    source_name: str | None = None


class ResolvedValueDto[T](ApiStruct):
    value: T
    provenance: ProvenanceDto


class EffectivePolicyRead(ApiStruct):
    dry_run: ResolvedValueDto[bool]
    target_languages: ResolvedValueDto[list[str]]
    source_preferences: ResolvedValueDto[list[str]]
    allow_hi_source: ResolvedValueDto[bool]
    allow_forced_source: ResolvedValueDto[bool]
    translate_hi_targets: ResolvedValueDto[bool]
    translate_forced_targets: ResolvedValueDto[bool]
    grace_hours_episodes: ResolvedValueDto[int]
    grace_hours_movies: ResolvedValueDto[int]
    skip_if_embedded_target: ResolvedValueDto[bool]
    skip_unmonitored: ResolvedValueDto[bool]
    priority_weights: ResolvedValueDto[PriorityWeightsDto]


def _provenance_dto(provenance: Provenance) -> ProvenanceDto:
    return ProvenanceDto(
        layer=provenance.layer,
        source_id=provenance.source_id,
        source_name=provenance.source_name,
    )


def _resolved_dto[T](resolved: Resolved[T]) -> ResolvedValueDto[T]:
    return ResolvedValueDto(
        value=resolved.value, provenance=_provenance_dto(resolved.provenance)
    )


def _resolved_list_dto(
    resolved: Resolved[tuple[str, ...]],
) -> ResolvedValueDto[list[str]]:
    return ResolvedValueDto(
        value=list(resolved.value), provenance=_provenance_dto(resolved.provenance)
    )


def effective_read(effective: EffectivePolicy) -> EffectivePolicyRead:
    return EffectivePolicyRead(
        dry_run=_resolved_dto(effective.dry_run),
        target_languages=_resolved_list_dto(effective.target_languages),
        source_preferences=_resolved_list_dto(effective.source_preferences),
        allow_hi_source=_resolved_dto(effective.allow_hi_source),
        allow_forced_source=_resolved_dto(effective.allow_forced_source),
        translate_hi_targets=_resolved_dto(effective.translate_hi_targets),
        translate_forced_targets=_resolved_dto(effective.translate_forced_targets),
        grace_hours_episodes=_resolved_dto(effective.grace_hours_episodes),
        grace_hours_movies=_resolved_dto(effective.grace_hours_movies),
        skip_if_embedded_target=_resolved_dto(effective.skip_if_embedded_target),
        skip_unmonitored=_resolved_dto(effective.skip_unmonitored),
        priority_weights=ResolvedValueDto(
            value=weights_dto(effective.priority_weights.value),
            provenance=_provenance_dto(effective.priority_weights.provenance),
        ),
    )


# --- export / import (FR-U6, §8.3) -------------------------------------------------


class PresetExport(ApiStruct):
    name: str
    description: str | None = None
    values: PolicyValuesDto | None = None
    rails: RailSettingsDto | None = None


class ProfileExport(ApiStruct):
    name: str
    description: str | None = None
    values: PolicyValuesDto | None = None


class PolicyExport(ApiStruct):
    schema_version: int
    presets: list[PresetExport]
    profiles: list[ProfileExport]


class PresetImport(ApiRequest):
    name: PolicyName
    description: str | None = None
    values: PolicyValuesRequest | None = None
    rails: RailSettingsDto | None = None


class ProfileImport(ApiRequest):
    name: PolicyName
    description: str | None = None
    values: PolicyValuesRequest | None = None


class PolicyImportRequest(ApiRequest):
    schema_version: Annotated[int, msgspec.Meta(ge=1)]
    presets: Annotated[list[PresetImport], msgspec.Meta(max_length=200)] = (
        msgspec.field(default_factory=list)
    )
    profiles: Annotated[list[ProfileImport], msgspec.Meta(max_length=200)] = (
        msgspec.field(default_factory=list)
    )


class PolicyImportResult(ApiStruct):
    created_presets: list[str]
    created_profiles: list[str]
    skipped: list[str]
