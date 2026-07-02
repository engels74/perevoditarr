"""Durable-evidence vocabulary and matchers for reconciliation (P2-T4).

Everything in this module describes evidence from the durable planes of
PRD §6.8 only — Bazarr metadata, Bazarr history (action 6 = translation),
Lingarr TranslationRequest records. Telemetry (Socket.IO/SignalR) has no
representation here by design (§7.3): these types are what an
`intent_event.evidence` snapshot is made of, and no telemetry payload can be
coerced into them.

Pure: imports msgspec and the integration *schemas* (plain data) only — no
sqlalchemy/litestar/httpx — so every matcher is unit-testable without DB or
HTTP.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import msgspec

from perevoditarr.modules.integrations.bazarr.schemas import (
    HISTORY_ACTION_TRANSLATED,
    EpisodeHistoryItem,
    MovieHistoryItem,
    SubtitleFile,
)
from perevoditarr.modules.integrations.lingarr.schemas import (
    ACTIVE_STATUSES,
    TranslationRequestRecord,
)
from perevoditarr.modules.policy import CODE2_CONVERSIONS


class SubtitlePresence(
    msgspec.Struct, tag="bazarr_metadata", kw_only=True, frozen=True
):
    """Does the target subtitle exist in Bazarr's metadata right now?

    `file_backed` is what supersession keys on: an embedded track was either
    already accounted for at discovery or deliberately not accepted by policy
    (skip_embedded_target=False means the user wants a real file), so only a
    file appearing means the intent's goal was met by other means.

    Deliberately carries no file path: this struct is persisted verbatim into
    `intent_event.evidence` and surfaced by the API, and Bazarr-host
    filesystem paths don't belong there (FR-A5 spirit).
    """

    present: bool
    file_backed: bool = False
    embedded_only: bool = False


class HistoryEvidence(msgspec.Struct, tag="bazarr_history", kw_only=True, frozen=True):
    """Was there a translation (action 6) history entry for this identity?"""

    translated: bool
    timestamp: str | None = None
    description: str | None = None


class LingarrRequestMatch(msgspec.Struct, kw_only=True, frozen=True):
    request_id: int
    status: str | None = None
    active: bool = False


class LingarrEvidence(
    msgspec.Struct, tag="lingarr_requests", kw_only=True, frozen=True
):
    """TranslationRequest records matched at §6.5 granularity.

    For episodes the identity is (show title, source→target pair) only — two
    episodes of one show on the same pair are indistinguishable, so a match
    set here can legitimately belong to any of them. Movies are exact.
    """

    matches: tuple[LingarrRequestMatch, ...] = ()

    @property
    def any_active(self) -> bool:
        return any(match.active for match in self.matches)


type DurableEvidence = SubtitlePresence | HistoryEvidence | LingarrEvidence


# ------------------------------------------------------------------ matchers


def subtitle_presence(
    subtitles: Sequence[SubtitleFile], *, language: str, forced: bool, hi: bool
) -> SubtitlePresence:
    file_backed = False
    embedded = False
    for subtitle in subtitles:
        if subtitle.code2 != language or subtitle.forced != forced or subtitle.hi != hi:
            continue
        if subtitle.path is not None:
            file_backed = True
        else:
            embedded = True
    if file_backed:
        return SubtitlePresence(present=True, file_backed=True)
    if embedded:
        return SubtitlePresence(present=True, embedded_only=True)
    return SubtitlePresence(present=False)


def parse_history_timestamp(raw: str | None) -> datetime | None:
    """Bazarr history timestamps vary by build (ISO string vs epoch); parse
    tolerantly — a shape we can't read is not a reason to drop evidence."""
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = datetime.fromtimestamp(float(raw), tz=UTC)
        except ValueError:
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def history_evidence(
    items: Sequence[EpisodeHistoryItem] | Sequence[MovieHistoryItem],
    *,
    language: str,
    forced: bool,
    hi: bool,
    since: datetime | None = None,
) -> HistoryEvidence:
    for item in items:
        if item.action != HISTORY_ACTION_TRANSLATED:
            continue
        entry_language = item.language
        if entry_language is None or entry_language.code2 != language:
            continue
        if entry_language.forced != forced or entry_language.hi != hi:
            continue
        timestamp = parse_history_timestamp(item.timestamp)
        # When a window is requested, an entry must provably fall inside it:
        # a missing/unparseable timestamp cannot corroborate "appeared via
        # translation *within* the window", so it counts as outside.
        if since is not None and (timestamp is None or timestamp < since):
            continue
        return HistoryEvidence(
            translated=True, timestamp=item.timestamp, description=item.description
        )
    return HistoryEvidence(translated=False)


def _lingarr_codes(code2: str) -> frozenset[str]:
    """Accept both the Bazarr code2 and its §6.3-converted form: Bazarr
    converts zh→zh-CN, zt→zh-TW, pb→pt-BR before calling Lingarr, so Lingarr
    records store the converted code."""
    converted = CODE2_CONVERSIONS.get(code2)
    return frozenset({code2, converted}) if converted else frozenset({code2})


def _match(record: TranslationRequestRecord) -> LingarrRequestMatch:
    return LingarrRequestMatch(
        request_id=record.id,
        status=record.status,
        active=(record.status or "") in ACTIVE_STATUSES,
    )


def lingarr_evidence_for_episode(
    records: Sequence[TranslationRequestRecord],
    *,
    display_title: str,
    source_language: str,
    target_language: str,
) -> LingarrEvidence:
    sources = _lingarr_codes(source_language)
    targets = _lingarr_codes(target_language)
    return LingarrEvidence(
        matches=tuple(
            _match(record)
            for record in records
            if record.media_type == "Episode"
            and record.title == display_title
            and (record.source_language or "") in sources
            and (record.target_language or "") in targets
        )
    )


def lingarr_evidence_for_movie(
    records: Sequence[TranslationRequestRecord],
    *,
    radarr_id: int,
    display_title: str,
    source_language: str,
    target_language: str,
) -> LingarrEvidence:
    sources = _lingarr_codes(source_language)
    targets = _lingarr_codes(target_language)
    return LingarrEvidence(
        matches=tuple(
            _match(record)
            for record in records
            if record.media_type == "Movie"
            # Movies are exactly identifiable (§6.5): the Radarr id must agree
            # when Lingarr resolved one; title+pair carries it otherwise.
            and (record.media_id is None or record.media_id == radarr_id)
            and record.title == display_title
            and (record.source_language or "") in sources
            and (record.target_language or "") in targets
        )
    )


# ------------------------------------------------------------ classification


class Supersede(msgspec.Struct, tag="supersede", kw_only=True, frozen=True):
    via_translation: bool
    detail: str


class NoChange(msgspec.Struct, tag="no_change", kw_only=True, frozen=True):
    pass


type BacklogOutcome = Supersede | NoChange


def classify_backlog(
    presence: SubtitlePresence, history: HistoryEvidence | None
) -> BacklogOutcome:
    """Observe-mode bookkeeping (FR-R2): a file-backed target subtitle
    appearing for a backlog intent means the goal was met by other means —
    indexer download, manual action, or an external translation (history
    action 6 tells which). Nothing here engages leases, retries, or dispatch;
    Phase 3 adds the dispatched-intent classification alongside."""
    if not presence.file_backed:
        return NoChange()
    if history is not None and history.translated:
        return Supersede(
            via_translation=True,
            detail="target subtitle appeared via translation (Bazarr history action 6)",
        )
    return Supersede(
        via_translation=False,
        detail="target subtitle appeared by other means",
    )
