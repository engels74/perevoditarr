"""Policy API controllers (P2-T1, FR-P1..P5 / FR-U6)."""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from litestar import Controller, delete, get, patch, post
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import DomainValidationError
from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.instances.gateway import InstanceGateway
from perevoditarr.modules.policy.resolver import (
    EpisodeRef,
    ItemRef,
    MovieRef,
    SeriesRef,
)
from perevoditarr.modules.policy.schemas import (
    EffectivePolicyRead,
    ExclusionCreate,
    ExclusionRead,
    OverrideRead,
    OverrideUpsert,
    PolicyExport,
    PolicyImportRequest,
    PolicyImportResult,
    PresetCreate,
    PresetFork,
    PresetRead,
    PresetUpdate,
    ProfileAssignmentCreate,
    ProfileAssignmentRead,
    ProfileEditorResponse,
    ProfileValidateRequest,
    ProfileValidateResponse,
    TranslationProfileCreate,
    TranslationProfileRead,
    TranslationProfileUpdate,
    effective_read,
)
from perevoditarr.modules.policy.service import PolicyService


async def provide_policy_service(
    db_session: AsyncSession, auth_runtime: AuthRuntime, gateway: InstanceGateway
) -> PolicyService:
    return PolicyService(db_session, auth_runtime.secret_box, gateway)


def _parse_tags(raw: str | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


class PolicyController(Controller):
    path: str = "/policy"
    tags: Sequence[str] | None = ("policy",)

    # --- presets ----------------------------------------------------------

    @get("/presets", operation_id="listPresets")
    async def list_presets(self, policy_service: PolicyService) -> list[PresetRead]:
        return await policy_service.list_presets()

    @post("/presets", operation_id="createPreset")
    async def create_preset(
        self, data: PresetCreate, policy_service: PolicyService
    ) -> PresetRead:
        return await policy_service.create_preset(data)

    @patch("/presets/{preset_id:uuid}", operation_id="updatePreset")
    async def update_preset(
        self, preset_id: UUID, data: PresetUpdate, policy_service: PolicyService
    ) -> PresetRead:
        return await policy_service.update_preset(preset_id, data)

    @delete("/presets/{preset_id:uuid}", operation_id="deletePreset")
    async def delete_preset(
        self, preset_id: UUID, policy_service: PolicyService
    ) -> None:
        await policy_service.delete_preset(preset_id)

    @post("/presets/{preset_id:uuid}/activate", operation_id="activatePreset")
    async def activate_preset(
        self, preset_id: UUID, policy_service: PolicyService
    ) -> PresetRead:
        return await policy_service.activate_preset(preset_id)

    @post("/presets/{preset_id:uuid}/fork", operation_id="forkPreset")
    async def fork_preset(
        self, preset_id: UUID, data: PresetFork, policy_service: PolicyService
    ) -> PresetRead:
        return await policy_service.fork_preset(preset_id, data.name)

    # --- export / import (FR-U6) -------------------------------------------

    @get("/export", operation_id="exportPolicies")
    async def export_policies(self, policy_service: PolicyService) -> PolicyExport:
        return await policy_service.export_policies()

    @post("/import", operation_id="importPolicies")
    async def import_policies(
        self, data: PolicyImportRequest, policy_service: PolicyService
    ) -> PolicyImportResult:
        return await policy_service.import_policies(data)

    # --- profiles -----------------------------------------------------------

    @get("/profiles", operation_id="listTranslationProfiles")
    async def list_profiles(
        self, policy_service: PolicyService
    ) -> list[TranslationProfileRead]:
        return await policy_service.list_profiles()

    @post("/profiles", operation_id="createTranslationProfile")
    async def create_profile(
        self, data: TranslationProfileCreate, policy_service: PolicyService
    ) -> ProfileEditorResponse:
        profile, findings = await policy_service.create_profile(data)
        return ProfileEditorResponse(profile=profile, findings=findings)

    @get("/profiles/{profile_id:uuid}", operation_id="getTranslationProfile")
    async def get_profile(
        self, profile_id: UUID, policy_service: PolicyService
    ) -> ProfileEditorResponse:
        profile, findings = await policy_service.profile_editor(profile_id)
        return ProfileEditorResponse(profile=profile, findings=findings)

    @patch("/profiles/{profile_id:uuid}", operation_id="updateTranslationProfile")
    async def update_profile(
        self,
        profile_id: UUID,
        data: TranslationProfileUpdate,
        policy_service: PolicyService,
    ) -> ProfileEditorResponse:
        profile, findings = await policy_service.update_profile(profile_id, data)
        return ProfileEditorResponse(profile=profile, findings=findings)

    @delete("/profiles/{profile_id:uuid}", operation_id="deleteTranslationProfile")
    async def delete_profile(
        self, profile_id: UUID, policy_service: PolicyService
    ) -> None:
        await policy_service.delete_profile(profile_id)

    @post("/profiles/validate", operation_id="validateProfileValues")
    async def validate_profile(
        self, data: ProfileValidateRequest, policy_service: PolicyService
    ) -> ProfileValidateResponse:
        return ProfileValidateResponse(
            findings=await policy_service.validate_values(data.values)
        )

    # --- assignments ----------------------------------------------------------

    @get("/assignments", operation_id="listProfileAssignments")
    async def list_assignments(
        self,
        policy_service: PolicyService,
        bazarr_instance_id: UUID | None = None,
        profile_id: UUID | None = None,
    ) -> list[ProfileAssignmentRead]:
        return await policy_service.list_assignments(
            bazarr_instance_id=bazarr_instance_id, profile_id=profile_id
        )

    @post("/assignments", operation_id="createProfileAssignment")
    async def create_assignment(
        self, data: ProfileAssignmentCreate, policy_service: PolicyService
    ) -> ProfileAssignmentRead:
        return await policy_service.create_assignment(data)

    @delete("/assignments/{assignment_id:uuid}", operation_id="deleteProfileAssignment")
    async def delete_assignment(
        self, assignment_id: UUID, policy_service: PolicyService
    ) -> None:
        await policy_service.delete_assignment(assignment_id)

    # --- exclusions --------------------------------------------------------------

    @get("/exclusions", operation_id="listExclusions")
    async def list_exclusions(
        self,
        policy_service: PolicyService,
        bazarr_instance_id: UUID | None = None,
    ) -> list[ExclusionRead]:
        return await policy_service.list_exclusions(
            bazarr_instance_id=bazarr_instance_id
        )

    @post("/exclusions", operation_id="createExclusion")
    async def create_exclusion(
        self, data: ExclusionCreate, policy_service: PolicyService
    ) -> ExclusionRead:
        return await policy_service.create_exclusion(data)

    @delete("/exclusions/{exclusion_id:uuid}", operation_id="deleteExclusion")
    async def delete_exclusion(
        self, exclusion_id: UUID, policy_service: PolicyService
    ) -> None:
        await policy_service.delete_exclusion(exclusion_id)

    # --- overrides -----------------------------------------------------------------

    @get("/overrides", operation_id="listOverrides")
    async def list_overrides(
        self,
        policy_service: PolicyService,
        bazarr_instance_id: UUID | None = None,
    ) -> list[OverrideRead]:
        return await policy_service.list_overrides(
            bazarr_instance_id=bazarr_instance_id
        )

    @post("/overrides", operation_id="upsertOverride")
    async def upsert_override(
        self, data: OverrideUpsert, policy_service: PolicyService
    ) -> OverrideRead:
        return await policy_service.upsert_override(data)

    @delete("/overrides/{override_id:uuid}", operation_id="deleteOverride")
    async def delete_override(
        self, override_id: UUID, policy_service: PolicyService
    ) -> None:
        await policy_service.delete_override(override_id)

    # --- effective policy inspector (§8.1 provenance) ----------------------------

    @get("/effective", operation_id="getEffectivePolicy")
    async def effective_policy(
        self,
        policy_service: PolicyService,
        bazarr_instance_id: UUID,
        media_type: Literal["series", "episode", "movie"],
        sonarr_series_id: int | None = None,
        sonarr_episode_id: int | None = None,
        radarr_id: int | None = None,
        tags: str | None = None,
        monitored: bool = True,
    ) -> EffectivePolicyRead:
        # The caller (library browser / discovery) supplies item context it
        # already holds; the cascade itself lives entirely in policy data.
        item: ItemRef
        match media_type:
            case "series":
                if sonarr_series_id is None:
                    raise DomainValidationError("sonarrSeriesId is required for series")
                item = SeriesRef(
                    bazarr_instance_id=bazarr_instance_id,
                    sonarr_series_id=sonarr_series_id,
                    tags=_parse_tags(tags),
                    monitored=monitored,
                )
            case "episode":
                if sonarr_series_id is None or sonarr_episode_id is None:
                    raise DomainValidationError(
                        "sonarrSeriesId and sonarrEpisodeId are required for episodes"
                    )
                item = EpisodeRef(
                    bazarr_instance_id=bazarr_instance_id,
                    sonarr_series_id=sonarr_series_id,
                    sonarr_episode_id=sonarr_episode_id,
                    tags=_parse_tags(tags),
                    monitored=monitored,
                )
            case "movie":
                if radarr_id is None:
                    raise DomainValidationError("radarrId is required for movies")
                item = MovieRef(
                    bazarr_instance_id=bazarr_instance_id,
                    radarr_id=radarr_id,
                    tags=_parse_tags(tags),
                    monitored=monitored,
                )
        return effective_read(await policy_service.effective_policy(item))
