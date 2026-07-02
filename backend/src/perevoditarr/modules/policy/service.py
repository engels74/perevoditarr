"""Policy domain service (P2-T1): preset/profile CRUD, cascade assembly,
inline validation, export/import.

ORM rows are converted to the resolver's plain structs here — nothing below
this layer sees the database, nothing above it sees raw JSON columns.
"""

from uuid import UUID

import msgspec
from advanced_alchemy.repository import SQLAlchemyAsyncRepository
from msgspec import UNSET
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PerevoditarrError,
)
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.instances.service import InstancesService
from perevoditarr.modules.policy.models import (
    Exclusion,
    Override,
    Preset,
    ProfileAssignment,
    TranslationProfile,
)
from perevoditarr.modules.policy.resolver import (
    AssignmentLayer,
    CascadeInput,
    EffectivePolicy,
    ExclusionRule,
    InstanceScope,
    ItemRef,
    LanguagePairExclusion,
    LayerSource,
    LibraryScope,
    MovieExclusion,
    MovieScope,
    MovieTarget,
    OverrideLayer,
    PolicyValues,
    SeriesExclusion,
    SeriesScope,
    SeriesTarget,
    TagExclusion,
    resolve_effective_policy,
)
from perevoditarr.modules.policy.schemas import (
    EXPORT_SCHEMA_VERSION,
    ExclusionCreate,
    ExclusionRead,
    OverrideRead,
    OverrideUpsert,
    PolicyExport,
    PolicyFindingRead,
    PolicyImportRequest,
    PolicyImportResult,
    PolicyValuesDto,
    PolicyValuesRequest,
    PresetCreate,
    PresetExport,
    PresetRead,
    PresetUpdate,
    ProfileAssignmentCreate,
    ProfileAssignmentRead,
    ProfileExport,
    RailSettingsDto,
    TranslationProfileCreate,
    TranslationProfileRead,
    TranslationProfileUpdate,
    finding_read,
    from_domain_values,
    to_domain_values,
)
from perevoditarr.modules.policy.validation import (
    LanguageInventory,
    ProfilePolicySummary,
    parse_lingarr_language_setting,
    validate_profile_values,
)


def _decode_json[T](raw: dict[str, object] | None, kind: type[T]) -> T | None:
    if raw is None:
        return None
    try:
        return msgspec.convert(raw, type=kind)
    except msgspec.ValidationError:
        # Rows written by a different build stay readable; the field simply
        # contributes nothing to the cascade.
        return None


def _encode_json(value: msgspec.Struct) -> dict[str, object]:
    return msgspec.json.decode(msgspec.json.encode(value), type=dict[str, object])


def _values_from_row(raw: dict[str, object] | None) -> PolicyValues:
    return _decode_json(raw, PolicyValues) or PolicyValues()


def preset_read(row: Preset) -> PresetRead:
    return PresetRead(
        id=row.id,
        name=row.name,
        description=row.description,
        built_in=row.built_in,
        active=row.active,
        values=from_domain_values(_values_from_row(row.values)),
        rails=_decode_json(row.rails, RailSettingsDto) or RailSettingsDto(),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def profile_read(
    row: TranslationProfile, assignment_count: int
) -> TranslationProfileRead:
    return TranslationProfileRead(
        id=row.id,
        name=row.name,
        description=row.description,
        values=from_domain_values(_values_from_row(row.values)),
        assignment_count=assignment_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def assignment_read(row: ProfileAssignment) -> ProfileAssignmentRead:
    scope = row.scope_type
    if scope not in ("instance", "library", "series", "movie"):
        raise DomainValidationError(f"unknown assignment scope {scope!r}")
    return ProfileAssignmentRead(
        id=row.id,
        profile_id=row.profile_id,
        profile_name=row.profile.name,
        bazarr_instance_id=row.bazarr_instance_id,
        scope_type=scope,
        scope_key=row.scope_key,
        created_at=row.created_at,
    )


def exclusion_read(row: Exclusion) -> ExclusionRead:
    kind = row.kind
    if kind not in ("series", "movie", "tag", "language_pair"):
        raise DomainValidationError(f"unknown exclusion kind {kind!r}")
    return ExclusionRead(
        id=row.id,
        bazarr_instance_id=row.bazarr_instance_id,
        kind=kind,
        rule_key=row.rule_key,
        note=row.note,
        created_at=row.created_at,
    )


def override_read(row: Override) -> OverrideRead:
    media_type = row.media_type
    if media_type not in ("series", "movie"):
        raise DomainValidationError(f"unknown override media type {media_type!r}")
    return OverrideRead(
        id=row.id,
        bazarr_instance_id=row.bazarr_instance_id,
        media_type=media_type,
        media_key=row.media_key,
        values=from_domain_values(_values_from_row(row.values)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def exclusion_rule(row: Exclusion) -> ExclusionRule:
    """DB row -> resolver rule. rule_key formats are service-validated."""
    match row.kind:
        case "series":
            return SeriesExclusion(
                exclusion_id=row.id, sonarr_series_id=int(row.rule_key)
            )
        case "movie":
            return MovieExclusion(exclusion_id=row.id, radarr_id=int(row.rule_key))
        case "tag":
            return TagExclusion(exclusion_id=row.id, tag_value=row.rule_key)
        case "language_pair":
            source, _, target = row.rule_key.partition("->")
            return LanguagePairExclusion(
                exclusion_id=row.id, source_language=source, target_language=target
            )
        case _:
            raise DomainValidationError(f"unknown exclusion kind {row.kind!r}")


def _assignment_scope(
    row: ProfileAssignment,
) -> InstanceScope | LibraryScope | SeriesScope | MovieScope:
    match row.scope_type:
        case "instance":
            return InstanceScope()
        case "library":
            return LibraryScope(tag_value=row.scope_key)
        case "series":
            return SeriesScope(sonarr_series_id=int(row.scope_key))
        case "movie":
            return MovieScope(radarr_id=int(row.scope_key))
        case _:
            raise DomainValidationError(f"unknown assignment scope {row.scope_type!r}")


class PresetRepository(SQLAlchemyAsyncRepository[Preset]):
    model_type: type[Preset] = Preset


class ProfileRepository(SQLAlchemyAsyncRepository[TranslationProfile]):
    model_type: type[TranslationProfile] = TranslationProfile


class PolicyService:
    def __init__(
        self, session: AsyncSession, secret_box: SecretBox, gateway: InstanceGateway
    ) -> None:
        self.session: AsyncSession = session
        self.secret_box: SecretBox = secret_box
        self.gateway: InstanceGateway = gateway
        self.presets: PresetRepository = PresetRepository(session=session)
        self.profiles: ProfileRepository = ProfileRepository(session=session)

    # ------------------------------------------------------------ presets

    async def list_presets(self) -> list[PresetRead]:
        rows = await self.presets.list(order_by=[("name", False)])
        return [preset_read(row) for row in rows]

    async def get_preset(self, preset_id: UUID) -> Preset:
        row = await self.presets.get_one_or_none(id=preset_id)
        if row is None:
            raise NotFoundError(f"preset {preset_id} not found")
        return row

    async def create_preset(self, data: PresetCreate) -> PresetRead:
        await self._ensure_unique_preset_name(data.name)
        row = Preset(
            name=data.name,
            description=data.description,
            built_in=False,
            active=False,
            values=(
                _encode_json(to_domain_values(data.values))
                if data.values is not None
                else None
            ),
            rails=_encode_json(data.rails) if data.rails is not None else None,
        )
        self.session.add(row)
        await self.session.commit()
        return preset_read(row)

    async def update_preset(self, preset_id: UUID, data: PresetUpdate) -> PresetRead:
        row = await self.get_preset(preset_id)
        if data.name is not UNSET and data.name != row.name:
            if row.built_in:
                raise ConflictError("built-in presets cannot be renamed")
            await self._ensure_unique_preset_name(data.name)
            row.name = data.name
        if data.description is not UNSET:
            row.description = data.description
        if data.values is not UNSET:
            row.values = _encode_json(to_domain_values(data.values))
        if data.rails is not UNSET:
            row.rails = _encode_json(data.rails)
        await self.session.commit()
        return preset_read(row)

    async def delete_preset(self, preset_id: UUID) -> None:
        row = await self.get_preset(preset_id)
        if row.built_in:
            raise ConflictError("built-in presets cannot be deleted (fork instead)")
        if row.active:
            raise ConflictError("activate another preset before deleting this one")
        await self.session.delete(row)
        await self.session.commit()

    async def activate_preset(self, preset_id: UUID) -> PresetRead:
        row = await self.get_preset(preset_id)
        # Exactly one active preset (§8.1); enforced here, asserted by tests.
        for other in await self.presets.list():
            other.active = other.id == row.id
        await self.session.commit()
        return preset_read(row)

    async def fork_preset(self, preset_id: UUID, name: str) -> PresetRead:
        source = await self.get_preset(preset_id)
        await self._ensure_unique_preset_name(name)
        row = Preset(
            name=name,
            description=source.description,
            built_in=False,
            active=False,
            values=dict(source.values) if source.values is not None else None,
            rails=dict(source.rails) if source.rails is not None else None,
        )
        self.session.add(row)
        await self.session.commit()
        return preset_read(row)

    async def active_preset(self) -> Preset | None:
        return (await self.session.scalars(select(Preset).where(Preset.active))).first()

    def preset_values(self, row: Preset) -> PolicyValues:
        """Decoded layer values for a preset row (public accessor: other
        modules never touch the raw JSON columns)."""
        return _values_from_row(row.values)

    def preset_rails(self, row: Preset) -> RailSettingsDto:
        """Decoded rail posture for a preset row (consumed by the plan
        preview now, the rails subsystem in P3-T1)."""
        return _decode_json(row.rails, RailSettingsDto) or RailSettingsDto()

    async def _ensure_unique_preset_name(self, name: str) -> None:
        existing = (
            await self.session.scalars(select(Preset.id).where(Preset.name == name))
        ).first()
        if existing is not None:
            raise ConflictError(f"a preset named {name!r} already exists")

    # ------------------------------------------------------------ profiles

    async def list_profiles(self) -> list[TranslationProfileRead]:
        rows = await self.profiles.list(order_by=[("name", False)])
        counts = dict(
            (
                await self.session.execute(
                    select(
                        ProfileAssignment.profile_id, func.count(ProfileAssignment.id)
                    ).group_by(ProfileAssignment.profile_id)
                )
            )
            .tuples()
            .all()
        )
        return [profile_read(row, counts.get(row.id, 0)) for row in rows]

    async def get_profile(self, profile_id: UUID) -> TranslationProfile:
        row = await self.profiles.get_one_or_none(id=profile_id)
        if row is None:
            raise NotFoundError(f"translation profile {profile_id} not found")
        return row

    async def _assignment_count(self, profile_id: UUID) -> int:
        count = (
            await self.session.execute(
                select(func.count(ProfileAssignment.id)).where(
                    ProfileAssignment.profile_id == profile_id
                )
            )
        ).scalar_one()
        return count

    async def create_profile(
        self, data: TranslationProfileCreate
    ) -> tuple[TranslationProfileRead, list[PolicyFindingRead]]:
        await self._ensure_unique_profile_name(data.name)
        values = to_domain_values(data.values) if data.values is not None else None
        row = TranslationProfile(
            name=data.name,
            description=data.description,
            values=_encode_json(values) if values is not None else None,
        )
        self.session.add(row)
        await self.session.commit()
        findings = await self.validate_values(values or PolicyValues())
        return profile_read(row, 0), findings

    async def update_profile(
        self, profile_id: UUID, data: TranslationProfileUpdate
    ) -> tuple[TranslationProfileRead, list[PolicyFindingRead]]:
        row = await self.get_profile(profile_id)
        if data.name is not UNSET and data.name != row.name:
            await self._ensure_unique_profile_name(data.name)
            row.name = data.name
        if data.description is not UNSET:
            row.description = data.description
        if data.values is not UNSET:
            row.values = _encode_json(to_domain_values(data.values))
        await self.session.commit()
        findings = await self.validate_values(_values_from_row(row.values))
        return profile_read(row, await self._assignment_count(profile_id)), findings

    async def profile_editor(
        self, profile_id: UUID
    ) -> tuple[TranslationProfileRead, list[PolicyFindingRead]]:
        row = await self.get_profile(profile_id)
        findings = await self.validate_values(_values_from_row(row.values))
        return profile_read(row, await self._assignment_count(profile_id)), findings

    async def delete_profile(self, profile_id: UUID) -> None:
        row = await self.get_profile(profile_id)
        await self.session.delete(row)  # assignments cascade
        await self.session.commit()

    async def _ensure_unique_profile_name(self, name: str) -> None:
        existing = (
            await self.session.scalars(
                select(TranslationProfile.id).where(TranslationProfile.name == name)
            )
        ).first()
        if existing is not None:
            raise ConflictError(f"a profile named {name!r} already exists")

    # ---------------------------------------------------- inline validation

    async def validate_values(
        self, values: PolicyValues | PolicyValuesRequest | PolicyValuesDto
    ) -> list[PolicyFindingRead]:
        domain = (
            values if isinstance(values, PolicyValues) else to_domain_values(values)
        )
        inventories = await self._language_inventories()
        return [finding_read(f) for f in validate_profile_values(domain, inventories)]

    async def _language_inventories(self) -> tuple[LanguageInventory, ...]:
        """Live per-instance language inventories, degrading gracefully:
        an unreachable instance yields None fields, never an error (FR-P4)."""
        instances = InstancesService(self.session, self.secret_box)
        inventories: list[LanguageInventory] = []
        for instance in await instances.list_bazarr():
            if not instance.enabled:
                continue
            bazarr_languages: frozenset[str] | None = None
            lingarr_sources: frozenset[str] | None = None
            lingarr_targets: frozenset[str] | None = None
            client = self.gateway.bazarr(
                instance.url, instances.bazarr_api_key(instance)
            )
            try:
                profiles = await client.languages_profiles()
            except PerevoditarrError:
                profiles = None
            if profiles is not None:
                bazarr_languages = frozenset(
                    item.language
                    for profile in profiles
                    for item in profile.items
                    if item.language
                )
            if instance.lingarr_instance_id is not None:
                lingarr_row = await instances.get_lingarr(instance.lingarr_instance_id)
                lingarr_client = self.gateway.lingarr(
                    lingarr_row.url, instances.lingarr_api_key(lingarr_row)
                )
                try:
                    settings = await lingarr_client.doctor_settings()
                except PerevoditarrError:
                    settings = None
                if settings is not None:
                    lingarr_sources = parse_lingarr_language_setting(
                        settings.get("source_languages")
                    )
                    lingarr_targets = parse_lingarr_language_setting(
                        settings.get("target_languages")
                    )
            inventories.append(
                LanguageInventory(
                    instance_name=instance.name,
                    bazarr_languages=bazarr_languages,
                    lingarr_sources=lingarr_sources,
                    lingarr_targets=lingarr_targets,
                )
            )
        return tuple(inventories)

    # ------------------------------------------------------------ assignments

    async def list_assignments(
        self,
        *,
        bazarr_instance_id: UUID | None = None,
        profile_id: UUID | None = None,
    ) -> list[ProfileAssignmentRead]:
        stmt = select(ProfileAssignment).order_by(ProfileAssignment.created_at)
        if bazarr_instance_id is not None:
            stmt = stmt.where(
                ProfileAssignment.bazarr_instance_id == bazarr_instance_id
            )
        if profile_id is not None:
            stmt = stmt.where(ProfileAssignment.profile_id == profile_id)
        rows = (await self.session.scalars(stmt)).all()
        return [assignment_read(row) for row in rows]

    async def create_assignment(
        self, data: ProfileAssignmentCreate
    ) -> ProfileAssignmentRead:
        _ = await self.get_profile(data.profile_id)
        instances = InstancesService(self.session, self.secret_box)
        _ = await instances.get_bazarr(data.bazarr_instance_id)
        self._validate_scope_key(data.scope_type, data.scope_key)
        existing = (
            await self.session.scalars(
                select(ProfileAssignment.id).where(
                    ProfileAssignment.bazarr_instance_id == data.bazarr_instance_id,
                    ProfileAssignment.scope_type == data.scope_type,
                    ProfileAssignment.scope_key == data.scope_key,
                )
            )
        ).first()
        if existing is not None:
            raise ConflictError(
                "this scope already has a profile assigned; remove it first"
            )
        row = ProfileAssignment(
            profile_id=data.profile_id,
            bazarr_instance_id=data.bazarr_instance_id,
            scope_type=data.scope_type,
            scope_key=data.scope_key,
        )
        self.session.add(row)
        await self.session.commit()
        return assignment_read(
            (
                await self.session.scalars(
                    select(ProfileAssignment).where(ProfileAssignment.id == row.id)
                )
            ).one()
        )

    async def delete_assignment(self, assignment_id: UUID) -> None:
        row = (
            await self.session.scalars(
                select(ProfileAssignment).where(ProfileAssignment.id == assignment_id)
            )
        ).first()
        if row is None:
            raise NotFoundError(f"assignment {assignment_id} not found")
        await self.session.delete(row)
        await self.session.commit()

    def _validate_scope_key(self, scope_type: str, scope_key: str) -> None:
        match scope_type:
            case "instance":
                if scope_key != "":
                    raise DomainValidationError(
                        "instance-scope assignments take no scopeKey"
                    )
            case "library":
                if not scope_key:
                    raise DomainValidationError(
                        "library-scope assignments need a tag as scopeKey"
                    )
            case "series" | "movie":
                if not scope_key.isdigit():
                    raise DomainValidationError(
                        f"{scope_type}-scope assignments take the arr id as scopeKey"
                    )
            case _:
                raise DomainValidationError(f"unknown scope type {scope_type!r}")

    # ------------------------------------------------------------ exclusions

    async def list_exclusions(
        self, *, bazarr_instance_id: UUID | None = None
    ) -> list[ExclusionRead]:
        stmt = select(Exclusion).order_by(Exclusion.created_at)
        if bazarr_instance_id is not None:
            stmt = stmt.where(Exclusion.bazarr_instance_id == bazarr_instance_id)
        return [exclusion_read(row) for row in (await self.session.scalars(stmt)).all()]

    async def create_exclusion(self, data: ExclusionCreate) -> ExclusionRead:
        instances = InstancesService(self.session, self.secret_box)
        _ = await instances.get_bazarr(data.bazarr_instance_id)
        self._validate_rule_key(data.kind, data.rule_key)
        existing = (
            await self.session.scalars(
                select(Exclusion.id).where(
                    Exclusion.bazarr_instance_id == data.bazarr_instance_id,
                    Exclusion.kind == data.kind,
                    Exclusion.rule_key == data.rule_key,
                )
            )
        ).first()
        if existing is not None:
            raise ConflictError("this exclusion already exists")
        row = Exclusion(
            bazarr_instance_id=data.bazarr_instance_id,
            kind=data.kind,
            rule_key=data.rule_key,
            note=data.note,
        )
        self.session.add(row)
        await self.session.commit()
        return exclusion_read(row)

    async def delete_exclusion(self, exclusion_id: UUID) -> None:
        row = (
            await self.session.scalars(
                select(Exclusion).where(Exclusion.id == exclusion_id)
            )
        ).first()
        if row is None:
            raise NotFoundError(f"exclusion {exclusion_id} not found")
        await self.session.delete(row)
        await self.session.commit()

    def _validate_rule_key(self, kind: str, rule_key: str) -> None:
        match kind:
            case "series" | "movie":
                if not rule_key.isdigit():
                    raise DomainValidationError(
                        f"{kind} exclusions take the arr id as ruleKey"
                    )
            case "tag":
                pass  # any non-empty string (min_length enforced at decode)
            case "language_pair":
                source, sep, target = rule_key.partition("->")
                if not sep or not source or not target:
                    raise DomainValidationError(
                        "language_pair exclusions use 'source->target' as ruleKey"
                    )
            case _:
                raise DomainValidationError(f"unknown exclusion kind {kind!r}")

    # ------------------------------------------------------------ overrides

    async def list_overrides(
        self, *, bazarr_instance_id: UUID | None = None
    ) -> list[OverrideRead]:
        stmt = select(Override).order_by(Override.created_at)
        if bazarr_instance_id is not None:
            stmt = stmt.where(Override.bazarr_instance_id == bazarr_instance_id)
        return [override_read(row) for row in (await self.session.scalars(stmt)).all()]

    async def upsert_override(self, data: OverrideUpsert) -> OverrideRead:
        instances = InstancesService(self.session, self.secret_box)
        _ = await instances.get_bazarr(data.bazarr_instance_id)
        if not data.media_key.isdigit():
            raise DomainValidationError("mediaKey is the arr id as a string")
        row = (
            await self.session.scalars(
                select(Override).where(
                    Override.bazarr_instance_id == data.bazarr_instance_id,
                    Override.media_type == data.media_type,
                    Override.media_key == data.media_key,
                )
            )
        ).first()
        if row is None:
            row = Override(
                bazarr_instance_id=data.bazarr_instance_id,
                media_type=data.media_type,
                media_key=data.media_key,
                values=_encode_json(to_domain_values(data.values)),
            )
            self.session.add(row)
        else:
            row.values = _encode_json(to_domain_values(data.values))
        await self.session.commit()
        return override_read(row)

    async def delete_override(self, override_id: UUID) -> None:
        row = (
            await self.session.scalars(
                select(Override).where(Override.id == override_id)
            )
        ).first()
        if row is None:
            raise NotFoundError(f"override {override_id} not found")
        await self.session.delete(row)
        await self.session.commit()

    # ------------------------------------------------------------ cascade

    async def cascade_input(self, bazarr_instance_id: UUID) -> CascadeInput:
        """Assemble the item-independent cascade layers for one instance."""
        preset_row = await self.active_preset()
        preset = (
            LayerSource(
                source_id=preset_row.id,
                source_name=preset_row.name,
                values=_values_from_row(preset_row.values),
            )
            if preset_row is not None
            else None
        )
        assignment_rows = (
            await self.session.scalars(
                select(ProfileAssignment)
                .where(ProfileAssignment.bazarr_instance_id == bazarr_instance_id)
                .order_by(ProfileAssignment.updated_at, ProfileAssignment.id)
            )
        ).all()
        assignments = tuple(
            AssignmentLayer(
                scope=_assignment_scope(row),
                profile=LayerSource(
                    source_id=row.profile.id,
                    source_name=row.profile.name,
                    values=_values_from_row(row.profile.values),
                ),
            )
            for row in assignment_rows
        )
        override_rows = (
            await self.session.scalars(
                select(Override)
                .where(Override.bazarr_instance_id == bazarr_instance_id)
                .order_by(Override.updated_at, Override.id)
            )
        ).all()
        overrides = tuple(
            OverrideLayer(
                target=(
                    SeriesTarget(sonarr_series_id=int(row.media_key))
                    if row.media_type == "series"
                    else MovieTarget(radarr_id=int(row.media_key))
                ),
                source=LayerSource(
                    source_id=row.id,
                    source_name=f"{row.media_type} override",
                    values=_values_from_row(row.values),
                ),
            )
            for row in override_rows
        )
        return CascadeInput(preset=preset, assignments=assignments, overrides=overrides)

    async def exclusion_rules(
        self, bazarr_instance_id: UUID
    ) -> tuple[ExclusionRule, ...]:
        rows = (
            await self.session.scalars(
                select(Exclusion).where(
                    Exclusion.bazarr_instance_id == bazarr_instance_id
                )
            )
        ).all()
        return tuple(exclusion_rule(row) for row in rows)

    async def effective_policy(self, item: ItemRef) -> EffectivePolicy:
        cascade = await self.cascade_input(item.bazarr_instance_id)
        return resolve_effective_policy(item, cascade)

    async def profile_summaries(self) -> tuple[ProfilePolicySummary, ...]:
        """Plain snapshots for the doctor's FR-DR4/FR-DR6 checks."""
        assigned: dict[UUID, list[UUID]] = {}
        rows = (
            await self.session.execute(
                select(
                    ProfileAssignment.profile_id, ProfileAssignment.bazarr_instance_id
                )
            )
        ).tuples()
        for profile_id, instance_id in rows:
            assigned.setdefault(profile_id, []).append(instance_id)
        return tuple(
            ProfilePolicySummary(
                profile_id=row.id,
                name=row.name,
                values=_values_from_row(row.values),
                instance_ids=tuple(assigned.get(row.id, ())),
            )
            for row in await self.profiles.list(order_by=[("name", False)])
        )

    # ------------------------------------------------------------ export/import

    async def export_policies(self) -> PolicyExport:
        presets = [
            PresetExport(
                name=row.name,
                description=row.description,
                values=(
                    from_domain_values(_values_from_row(row.values))
                    if row.values is not None
                    else None
                ),
                rails=_decode_json(row.rails, RailSettingsDto),
            )
            for row in await self.presets.list(order_by=[("name", False)])
        ]
        profiles = [
            ProfileExport(
                name=row.name,
                description=row.description,
                values=(
                    from_domain_values(_values_from_row(row.values))
                    if row.values is not None
                    else None
                ),
            )
            for row in await self.profiles.list(order_by=[("name", False)])
        ]
        return PolicyExport(
            schema_version=EXPORT_SCHEMA_VERSION, presets=presets, profiles=profiles
        )

    async def import_policies(self, data: PolicyImportRequest) -> PolicyImportResult:
        if data.schema_version != EXPORT_SCHEMA_VERSION:
            raise DomainValidationError(
                f"unsupported export schemaVersion {data.schema_version} (this build reads version {EXPORT_SCHEMA_VERSION})"
            )
        created_presets: list[str] = []
        created_profiles: list[str] = []
        skipped: list[str] = []
        for preset in data.presets:
            if await self._name_taken(Preset, preset.name):
                skipped.append(f"preset:{preset.name}")
                continue
            self.session.add(
                Preset(
                    name=preset.name,
                    description=preset.description,
                    built_in=False,
                    active=False,  # imported posture never auto-activates (G4)
                    values=(
                        _encode_json(to_domain_values(preset.values))
                        if preset.values is not None
                        else None
                    ),
                    rails=(
                        _encode_json(preset.rails) if preset.rails is not None else None
                    ),
                )
            )
            created_presets.append(preset.name)
        for profile in data.profiles:
            if await self._name_taken(TranslationProfile, profile.name):
                skipped.append(f"profile:{profile.name}")
                continue
            self.session.add(
                TranslationProfile(
                    name=profile.name,
                    description=profile.description,
                    values=(
                        _encode_json(to_domain_values(profile.values))
                        if profile.values is not None
                        else None
                    ),
                )
            )
            created_profiles.append(profile.name)
        await self.session.commit()
        return PolicyImportResult(
            created_presets=created_presets,
            created_profiles=created_profiles,
            skipped=skipped,
        )

    async def _name_taken(
        self, model: type[Preset] | type[TranslationProfile], name: str
    ) -> bool:
        found = (
            await self.session.scalars(select(model.id).where(model.name == name))
        ).first()
        return found is not None
