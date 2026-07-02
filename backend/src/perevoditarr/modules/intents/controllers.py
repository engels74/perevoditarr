"""Intent ledger API (P2-T2): read-only in Phase 2 (Observe posture).

List/filter, backlog and in-flight views, and per-intent detail with the full
event history and rendered decision trace. Mutations toward the ledger arrive
with FR-R6 in Phase 3.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from litestar import Controller, Request, get, post
from litestar.datastructures import State
from litestar.params import Parameter
from sqlalchemy.ext.asyncio import AsyncSession

from perevoditarr.core.errors import DomainValidationError
from perevoditarr.core.schemas import Page
from perevoditarr.core.sse import SseBus
from perevoditarr.modules.auth import AuthRuntime
from perevoditarr.modules.auth.models import User
from perevoditarr.modules.instances import InstanceGateway
from perevoditarr.modules.intents.discovery import DiscoveryService
from perevoditarr.modules.intents.discovery_rules import NotPlanned, Planned
from perevoditarr.modules.intents.passthrough import PassthroughService
from perevoditarr.modules.intents.schemas import (
    ExplainRead,
    IntentDetail,
    IntentRead,
    PassthroughActionRead,
    TimelineResponse,
)
from perevoditarr.modules.intents.service import IntentsService
from perevoditarr.modules.intents.state_machine import IntentState
from perevoditarr.modules.intents.timeline import TimelineService
from perevoditarr.modules.intents.trace import render_human, render_step

# Parameter metadata is inlined at each use site rather than held in PEP 695
# `type` aliases: Litestar's signature model does not see Parameter metadata
# through TypeAliasType, so aliased constraints are silently unenforced
# (same fix as dispatch/controllers).


async def provide_intents_service(db_session: AsyncSession) -> IntentsService:
    return IntentsService(db_session)


async def provide_discovery_service(
    db_session: AsyncSession,
    auth_runtime: AuthRuntime,
    gateway: InstanceGateway,
    sse_bus: SseBus,
) -> DiscoveryService:
    return DiscoveryService(db_session, auth_runtime.secret_box, gateway, sse_bus)


async def provide_timeline_service(
    db_session: AsyncSession, auth_runtime: AuthRuntime, gateway: InstanceGateway
) -> TimelineService:
    return TimelineService(db_session, auth_runtime.secret_box, gateway)


async def provide_passthrough_service(
    db_session: AsyncSession, auth_runtime: AuthRuntime, gateway: InstanceGateway
) -> PassthroughService:
    return PassthroughService(db_session, auth_runtime.secret_box, gateway)


def _parse_states(raw: str | None) -> list[IntentState] | None:
    if raw is None:
        return None
    states: list[IntentState] = []
    for part in raw.split(","):
        name = part.strip()
        if not name:
            continue
        try:
            states.append(IntentState(name))
        except ValueError:
            valid = ", ".join(state.value for state in IntentState)
            raise DomainValidationError(
                f"unknown intent state {name!r} (valid: {valid})"
            ) from None
    return states or None


class IntentsController(Controller):
    path: str = "/intents"
    tags: Sequence[str] | None = ("intents",)

    @get(operation_id="listIntents")
    async def list_intents(
        self,
        intents_service: IntentsService,
        # NB: named `states`, not `state` — `state` is a Litestar reserved
        # kwarg (injects the application State object).
        states: Annotated[
            str | None,
            Parameter(
                description="Comma-separated intent states, e.g. `discovered,eligible`"
            ),
        ] = None,
        bazarr_instance_id: UUID | None = None,
        media_type: Literal["episode", "movie"] | None = None,
        target_language: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: Annotated[int, Parameter(ge=1, le=500)] = 50,
        offset: Annotated[int, Parameter(ge=0)] = 0,
    ) -> Page[IntentRead]:
        return await intents_service.history(
            states=_parse_states(states),
            bazarr_instance_id=bazarr_instance_id,
            media_type=media_type,
            target_language=target_language,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
            offset=offset,
        )

    @get("/backlog", operation_id="listIntentBacklog")
    async def backlog(
        self,
        intents_service: IntentsService,
        bazarr_instance_id: UUID | None = None,
        limit: Annotated[int, Parameter(ge=1, le=500)] = 50,
        offset: Annotated[int, Parameter(ge=0)] = 0,
    ) -> Page[IntentRead]:
        return await intents_service.backlog(
            bazarr_instance_id=bazarr_instance_id, limit=limit, offset=offset
        )

    @get("/in-flight", operation_id="listIntentsInFlight")
    async def in_flight(
        self,
        intents_service: IntentsService,
        bazarr_instance_id: UUID | None = None,
        limit: Annotated[int, Parameter(ge=1, le=500)] = 50,
        offset: Annotated[int, Parameter(ge=0)] = 0,
    ) -> Page[IntentRead]:
        return await intents_service.in_flight(
            bazarr_instance_id=bazarr_instance_id, limit=limit, offset=offset
        )

    @get("/explain", operation_id="explainCandidate")
    async def explain(
        self,
        discovery_service: DiscoveryService,
        bazarr_instance_id: UUID,
        media_type: Literal["episode", "movie"],
        external_media_id: int,
        language: str,
        forced: bool = False,
        hi: bool = False,
    ) -> ExplainRead:
        decision = await discovery_service.explain_wanted(
            bazarr_instance_id,
            media_type=media_type,
            external_media_id=external_media_id,
            language=language,
            forced=forced,
            hi=hi,
        )
        match decision:
            case Planned(source_language=source, trace=trace):
                return ExplainRead(
                    outcome="planned",
                    reason=None,
                    detail=None,
                    source_language=source,
                    trace_rendered=render_human(trace),
                    trace_steps=[render_step(step) for step in trace],
                )
            case NotPlanned(reason=reason, detail=detail, trace=trace):
                return ExplainRead(
                    outcome="not_planned",
                    reason=reason,
                    detail=detail,
                    source_language=None,
                    trace_rendered=render_human(trace),
                    trace_steps=[render_step(step) for step in trace],
                )
            case None:
                return ExplainRead(
                    outcome="not_wanted",
                    reason="not_wanted",
                    detail="Bazarr does not list this subtitle as missing",
                    source_language=None,
                    trace_rendered="",
                    trace_steps=[],
                )

    @get("/{intent_id:uuid}", operation_id="getIntent")
    async def get_intent(
        self, intent_id: UUID, intents_service: IntentsService
    ) -> IntentDetail:
        return await intents_service.detail(intent_id)

    @get("/{intent_id:uuid}/timeline", operation_id="getIntentTimeline")
    async def timeline(
        self, intent_id: UUID, timeline_service: TimelineService
    ) -> TimelineResponse:
        return await timeline_service.timeline(intent_id)

    @post(
        "/{intent_id:uuid}/lingarr/{lingarr_request_id:int}/{action:str}",
        operation_id="lingarrPassthroughAction",
    )
    async def lingarr_passthrough(
        self,
        request: Request[User, object, State],
        intent_id: UUID,
        lingarr_request_id: int,
        action: str,
        passthrough_service: PassthroughService,
    ) -> PassthroughActionRead:
        return await passthrough_service.act(
            intent_id,
            lingarr_request_id,
            action,
            actor=f"user:{request.user.username}",
        )
