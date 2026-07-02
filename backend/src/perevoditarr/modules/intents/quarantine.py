"""Quarantine store + APIs (P3-T3, FR-R6): operator actions on stuck intents.

Two surfaces the queue UI (P3-T7) reads: *quarantined* intents (poison —
deterministic repeated failure, awaiting a decision) and *needs-attention*
intents (environmental failures parked without retry burn). The three actions —
retry (re-eligibilize), release (close), exclude (close + add a policy
exclusion so it never re-discovers) — go through the manual-transition allowlist
so automated processes can never take these edges.
"""

import contextlib
from collections.abc import Sequence
from typing import Annotated, Literal
from uuid import UUID

from litestar import Controller, get, post
from litestar.params import Parameter
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import ConflictError, DomainValidationError
from perevoditarr.core.schemas import Page
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.instances import InstanceGateway
from perevoditarr.modules.intents.schemas import IntentRead
from perevoditarr.modules.intents.service import IntentsService, intent_read
from perevoditarr.modules.intents.state_machine import (
    IllegalIntentTransition,
    IntentState,
)
from perevoditarr.modules.policy import PolicyService
from perevoditarr.modules.policy.schemas import ExclusionCreate


class QuarantineService:
    def __init__(
        self, session: AsyncSession, secret_box: SecretBox, gateway: InstanceGateway
    ) -> None:
        self.intents: IntentsService = IntentsService(session)
        self.policy: PolicyService = PolicyService(session, secret_box, gateway)

    async def list_quarantined(
        self, *, bazarr_instance_id: UUID | None, limit: int, offset: int
    ) -> Page[IntentRead]:
        return await self.intents.history(
            states=[IntentState.QUARANTINED],
            bazarr_instance_id=bazarr_instance_id,
            limit=limit,
            offset=offset,
        )

    async def list_needs_attention(
        self, *, bazarr_instance_id: UUID | None, limit: int, offset: int
    ) -> Page[IntentRead]:
        return await self.intents.history(
            states=[IntentState.FAILED],
            bazarr_instance_id=bazarr_instance_id,
            limit=limit,
            offset=offset,
        )

    async def retry(self, intent_id: UUID) -> IntentRead:
        intent = await self.intents.get(intent_id)
        try:
            _ = await self.intents.manual_transition(
                intent,
                IntentState.ELIGIBLE,
                actor="user:retry",
                reason="manual retry from quarantine",
            )
        except IllegalIntentTransition as error:
            raise ConflictError("only quarantined intents can be retried") from error
        return intent_read(intent)

    async def release(self, intent_id: UUID) -> IntentRead:
        intent = await self.intents.get(intent_id)
        try:
            _ = await self.intents.manual_transition(
                intent,
                IntentState.SUPERSEDED,
                actor="user:release",
                reason="released from quarantine without retry",
            )
        except IllegalIntentTransition as error:
            raise ConflictError("only quarantined intents can be released") from error
        return intent_read(intent)

    async def exclude(self, intent_id: UUID) -> IntentRead:
        intent = await self.intents.get(intent_id)
        kind: Literal["series", "movie"]
        if intent.media_type == "episode":
            if intent.sonarr_series_id is None:
                raise DomainValidationError(
                    "episode intent has no series id to exclude"
                )
            kind, rule_key = "series", str(intent.sonarr_series_id)
        else:
            kind, rule_key = "movie", str(intent.external_media_id)
        # Already excluded is fine — proceed to close the intent.
        with contextlib.suppress(ConflictError):
            _ = await self.policy.create_exclusion(
                ExclusionCreate(
                    bazarr_instance_id=intent.bazarr_instance_id,
                    kind=kind,
                    rule_key=rule_key,
                    note="excluded from the quarantine view",
                )
            )
        try:
            _ = await self.intents.manual_transition(
                intent,
                IntentState.SUPERSEDED,
                actor="user:exclude",
                reason=f"excluded {kind} {rule_key} and released from quarantine",
            )
        except IllegalIntentTransition as error:
            raise ConflictError("only quarantined intents can be excluded") from error
        return intent_read(intent)


async def provide_quarantine_service(
    db_session: AsyncSession, auth_runtime: AuthRuntime, gateway: InstanceGateway
) -> QuarantineService:
    return QuarantineService(db_session, auth_runtime.secret_box, gateway)


class QuarantineController(Controller):
    path: str = "/quarantine"
    tags: Sequence[str] | None = ("quarantine",)

    @get(operation_id="listQuarantine")
    async def list_quarantine(
        self,
        quarantine_service: QuarantineService,
        bazarr_instance_id: UUID | None = None,
        limit: Annotated[int, Parameter(ge=1, le=500)] = 50,
        offset: Annotated[int, Parameter(ge=0)] = 0,
    ) -> Page[IntentRead]:
        return await quarantine_service.list_quarantined(
            bazarr_instance_id=bazarr_instance_id, limit=limit, offset=offset
        )

    @get("/needs-attention", operation_id="listNeedsAttention")
    async def list_needs_attention(
        self,
        quarantine_service: QuarantineService,
        bazarr_instance_id: UUID | None = None,
        limit: Annotated[int, Parameter(ge=1, le=500)] = 50,
        offset: Annotated[int, Parameter(ge=0)] = 0,
    ) -> Page[IntentRead]:
        return await quarantine_service.list_needs_attention(
            bazarr_instance_id=bazarr_instance_id, limit=limit, offset=offset
        )

    @post("/{intent_id:uuid}/retry", operation_id="retryQuarantinedIntent")
    async def retry(
        self, intent_id: UUID, quarantine_service: QuarantineService
    ) -> IntentRead:
        return await quarantine_service.retry(intent_id)

    @post("/{intent_id:uuid}/release", operation_id="releaseQuarantinedIntent")
    async def release(
        self, intent_id: UUID, quarantine_service: QuarantineService
    ) -> IntentRead:
        return await quarantine_service.release(intent_id)

    @post("/{intent_id:uuid}/exclude", operation_id="excludeQuarantinedIntent")
    async def exclude(
        self, intent_id: UUID, quarantine_service: QuarantineService
    ) -> IntentRead:
        return await quarantine_service.exclude(intent_id)
