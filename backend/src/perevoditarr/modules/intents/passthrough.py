"""Lingarr pass-through actions (P4-T2, FR-X3): user-initiated cancel / retry /
resume / remove, mapped 1:1 to Lingarr's own endpoints and always audit-logged.

This is a deliberate, user-only write surface (§7.5): it never runs
automatically and never touches Bazarr. Each attempt writes a `passthrough_action`
row (who, what, whether Lingarr accepted it) so the item timeline (P4-T2) shows
the full provenance. An upstream rejection is recorded as `failed` and returned
to the caller — it is a real outcome, not a 500.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import (
    ConflictError,
    DomainValidationError,
    NotFoundError,
    PerevoditarrError,
)
from perevoditarr.core.security import SecretBox
from perevoditarr.modules.instances import InstanceGateway, InstancesService
from perevoditarr.modules.integrations.lingarr import (
    LingarrClient,
    TranslationRequestRecord,
)
from perevoditarr.modules.intents.evidence import (
    matching_lingarr_records_episode,
    matching_lingarr_records_movie,
)
from perevoditarr.modules.intents.models import Intent, PassthroughAction
from perevoditarr.modules.intents.schemas import PassthroughActionRead

VALID_ACTIONS: frozenset[str] = frozenset({"cancel", "retry", "resume", "remove"})


def _action_read(row: PassthroughAction) -> PassthroughActionRead:
    return PassthroughActionRead(
        id=row.id,
        intent_id=row.intent_id,
        lingarr_request_id=row.lingarr_request_id,
        action=row.action,
        actor=row.actor,
        status=row.status,
        detail=row.detail,
        created_at=row.created_at,
    )


class PassthroughService:
    def __init__(
        self, session: AsyncSession, secret_box: SecretBox, gateway: InstanceGateway
    ) -> None:
        self.session: AsyncSession = session
        self.gateway: InstanceGateway = gateway
        self.instances: InstancesService = InstancesService(session, secret_box)

    async def act(
        self,
        intent_id: UUID,
        lingarr_request_id: int,
        action: str,
        *,
        actor: str,
    ) -> PassthroughActionRead:
        if action not in VALID_ACTIONS:
            raise DomainValidationError(
                f"unknown pass-through action {action!r}; expected one of "
                + f"{sorted(VALID_ACTIONS)}"
            )
        intent = await self._get_intent(intent_id)
        instance = await self.instances.get_bazarr(intent.bazarr_instance_id)
        if instance.lingarr_instance_id is None:
            raise ConflictError("this Bazarr instance has no linked Lingarr to act on")
        lingarr = await self.instances.get_lingarr(instance.lingarr_instance_id)
        client = self.gateway.lingarr(
            lingarr.url, self.instances.lingarr_api_key(lingarr)
        )
        # request_detail failing (e.g. 404) is a genuine error before any audit
        # — we never acted, so nothing is logged.
        record = await client.request_detail(lingarr_request_id)
        # The id is an arbitrary caller-supplied path param, so confirm the
        # fetched record actually belongs to this intent (§6.5 matchers) before
        # we act on it or audit-log it against intent_id — otherwise a caller
        # could act on and mis-attribute an unrelated Lingarr request.
        if intent.media_type == "episode":
            matched = matching_lingarr_records_episode(
                [record],
                display_title=intent.display_title,
                source_language=intent.source_language,
                target_language=intent.target_language,
            )
        else:
            matched = matching_lingarr_records_movie(
                [record],
                radarr_id=intent.external_media_id,
                display_title=intent.display_title,
                source_language=intent.source_language,
                target_language=intent.target_language,
            )
        if not matched:
            raise NotFoundError(
                f"Lingarr request {lingarr_request_id} is not associated with "
                + f"intent {intent_id}"
            )

        status = "ok"
        detail: str | None = None
        try:
            await _invoke(client, action, record)
        except PerevoditarrError as error:
            status = "failed"
            detail = str(error)

        row = PassthroughAction(
            intent_id=intent.id,
            lingarr_request_id=lingarr_request_id,
            action=action,
            actor=actor,
            status=status,
            detail=detail,
        )
        self.session.add(row)
        await self.session.commit()
        return _action_read(row)

    async def _get_intent(self, intent_id: UUID) -> Intent:
        intent = await self.session.get(Intent, intent_id)
        if intent is None:
            raise NotFoundError(f"intent {intent_id} not found")
        return intent


async def _invoke(
    client: LingarrClient, action: str, record: TranslationRequestRecord
) -> None:
    actions: dict[str, Callable[[TranslationRequestRecord], Awaitable[None]]] = {
        "cancel": client.cancel_request,
        "retry": client.retry_request,
        "resume": client.resume_request,
        "remove": client.remove_request,
    }
    await actions[action](record)
