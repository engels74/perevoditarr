"""Intent API DTOs (P2-T2). camelCase on the wire via ApiStruct.

Read-only in Phase 2 (Observe): the ledger is inspected, never mutated from
the API — manual intent actions are FR-R6 (Phase 3).
"""

from datetime import datetime
from uuid import UUID

from perevoditarr.core.schemas import ApiStruct


class IntentRead(ApiStruct):
    id: UUID
    bazarr_instance_id: UUID
    media_type: str
    external_media_id: int
    sonarr_series_id: int | None
    season: int | None
    episode_number: int | None
    display_title: str
    source_language: str
    target_language: str
    forced: bool
    hi: bool
    state: str
    lease_expires_at: datetime | None
    priority: int
    bumped_at: datetime | None
    trace_rendered: str
    created_at: datetime
    updated_at: datetime


class IntentEventRead(ApiStruct):
    id: UUID
    actor: str
    from_state: str | None
    to_state: str
    reason: str
    evidence: dict[str, object] | None
    created_at: datetime


class IntentDetail(ApiStruct):
    intent: IntentRead
    trace_steps: list[str]
    events: list[IntentEventRead]


class ExplainRead(ApiStruct):
    """One wanted item's rule-chain outcome — the "why (not) planned?" answer.

    `outcome="not_wanted"` means Bazarr does not currently list the subtitle
    as missing, so discovery never evaluates it.
    """

    outcome: str  # planned | not_planned | not_wanted
    reason: str | None
    detail: str | None
    source_language: str | None
    trace_rendered: str
    trace_steps: list[str]
