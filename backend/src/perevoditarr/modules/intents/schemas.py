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


# --- Item timeline (P4-T2, FR-V4) -------------------------------------------
# A tagged union on the wire (discriminator `type`): the UI mirrors it as a
# discriminated union. Every source is stitched into one chronological stream.


class TimelineIntentEventEntry(ApiStruct, tag="intent_event"):
    at: datetime
    actor: str
    from_state: str | None
    to_state: str
    reason: str


class TimelineBazarrHistoryEntry(ApiStruct, tag="bazarr_history"):
    at: datetime | None
    action: int
    description: str | None
    language: str | None
    subtitles_path: str | None


class TimelineLingarrRequestEntry(ApiStruct, tag="lingarr_request"):
    at: datetime | None
    request_id: int
    status: str | None
    source_language: str | None
    target_language: str | None
    error_message: str | None
    completed_at: datetime | None
    active: bool


class TimelinePassthroughEntry(ApiStruct, tag="passthrough_action"):
    at: datetime
    action: str
    actor: str
    status: str
    detail: str | None
    lingarr_request_id: int


type TimelineEntryDto = (
    TimelineIntentEventEntry
    | TimelineBazarrHistoryEntry
    | TimelineLingarrRequestEntry
    | TimelinePassthroughEntry
)


class TimelineResponse(ApiStruct):
    intent: IntentRead
    # Which upstream sources were reachable while stitching (unreachable ones
    # degrade gracefully — their absence is noted, never an error).
    bazarr_history_available: bool
    lingarr_available: bool
    entries: list[TimelineEntryDto]


# --- Lingarr pass-through actions (P4-T2, FR-X3) ----------------------------


class PassthroughActionRead(ApiStruct):
    id: UUID
    intent_id: UUID
    lingarr_request_id: int
    action: str
    actor: str
    status: str
    detail: str | None
    created_at: datetime
