"""Pure evidence matchers and Observe-mode classification (P2-T4).

No DB, no HTTP: these exercise the §6.8 durable-evidence vocabulary directly,
including the §6.5 coarseness corner (two episodes of one show on the same
pair are indistinguishable in Lingarr) and the §6.3 code-conversion cases.
"""

from datetime import UTC, datetime, timedelta

from perevoditarr.modules.integrations.bazarr.schemas import (
    EpisodeHistoryItem,
    SubtitleFile,
    SubtitleLanguage,
)
from perevoditarr.modules.integrations.lingarr.schemas import TranslationRequestRecord
from perevoditarr.modules.intents.evidence import (
    HistoryEvidence,
    NoChange,
    SubtitlePresence,
    Supersede,
    classify_backlog,
    history_evidence,
    lingarr_evidence_for_episode,
    lingarr_evidence_for_movie,
    parse_history_timestamp,
    subtitle_presence,
)

NOW = datetime(2026, 7, 2, 12, 0, tzinfo=UTC)


def _sub(
    code2: str,
    *,
    path: str | None = "/subs/x.srt",
    forced: bool = False,
    hi: bool = False,
) -> SubtitleFile:
    return SubtitleFile(code2=code2, path=path, forced=forced, hi=hi)


def _history_item(
    *,
    action: int = 6,
    code2: str = "da",
    forced: bool = False,
    hi: bool = False,
    timestamp: str | None = None,
) -> EpisodeHistoryItem:
    return EpisodeHistoryItem(
        action=action,
        timestamp=timestamp,
        language=SubtitleLanguage(code2=code2, forced=forced, hi=hi),
    )


def _request(
    *,
    request_id: int = 1,
    media_id: int | None = None,
    title: str = "Alpha Show",
    source: str = "en",
    target: str = "da",
    media_type: str = "Episode",
    status: str = "Pending",
) -> TranslationRequestRecord:
    return TranslationRequestRecord(
        id=request_id,
        media_id=media_id,
        title=title,
        source_language=source,
        target_language=target,
        media_type=media_type,
        status=status,
    )


class TestSubtitlePresence:
    def test_file_backed_match(self) -> None:
        presence = subtitle_presence(
            [_sub("en"), _sub("da", path="/subs/x.da.srt")],
            language="da",
            forced=False,
            hi=False,
        )
        assert presence == SubtitlePresence(present=True, file_backed=True)

    def test_forced_and_hi_must_match_exactly(self) -> None:
        subtitles = [_sub("da", forced=True), _sub("da", hi=True)]
        assert not subtitle_presence(
            subtitles, language="da", forced=False, hi=False
        ).present
        assert subtitle_presence(
            subtitles, language="da", forced=True, hi=False
        ).file_backed

    def test_embedded_only_is_present_but_not_file_backed(self) -> None:
        presence = subtitle_presence(
            [_sub("da", path=None)], language="da", forced=False, hi=False
        )
        assert presence.present
        assert presence.embedded_only
        assert not presence.file_backed

    def test_file_wins_over_embedded(self) -> None:
        presence = subtitle_presence(
            [_sub("da", path=None), _sub("da", path="/subs/x.da.srt")],
            language="da",
            forced=False,
            hi=False,
        )
        assert presence.file_backed
        assert not presence.embedded_only

    def test_absent(self) -> None:
        assert subtitle_presence([], language="da", forced=False, hi=False) == (
            SubtitlePresence(present=False)
        )


class TestHistoryEvidence:
    def test_action_6_with_matching_language(self) -> None:
        evidence = history_evidence(
            [_history_item(timestamp=NOW.isoformat())],
            language="da",
            forced=False,
            hi=False,
        )
        assert evidence.translated

    def test_other_actions_do_not_count(self) -> None:
        evidence = history_evidence(
            [_history_item(action=1)], language="da", forced=False, hi=False
        )
        assert not evidence.translated

    def test_language_and_flags_must_match(self) -> None:
        items = [_history_item(code2="en"), _history_item(forced=True)]
        assert not history_evidence(
            items, language="da", forced=False, hi=False
        ).translated

    def test_window_excludes_entries_before_since(self) -> None:
        old = _history_item(timestamp=(NOW - timedelta(days=2)).isoformat())
        assert not history_evidence(
            [old], language="da", forced=False, hi=False, since=NOW - timedelta(days=1)
        ).translated
        assert history_evidence(
            [old], language="da", forced=False, hi=False, since=NOW - timedelta(days=3)
        ).translated

    def test_unparseable_timestamp_is_outside_a_requested_window(self) -> None:
        # An entry that can't prove it falls inside the window must not
        # corroborate "appeared via translation within the window".
        evidence = history_evidence(
            [_history_item(timestamp="not-a-time")],
            language="da",
            forced=False,
            hi=False,
            since=NOW,
        )
        assert not evidence.translated

    def test_unparseable_timestamp_counts_when_no_window_requested(self) -> None:
        evidence = history_evidence(
            [_history_item(timestamp="not-a-time")],
            language="da",
            forced=False,
            hi=False,
        )
        assert evidence.translated

    def test_timestamp_parsing_variants(self) -> None:
        assert parse_history_timestamp(NOW.isoformat()) == NOW
        epoch = parse_history_timestamp(str(NOW.timestamp()))
        assert epoch == NOW
        assert parse_history_timestamp("garbage") is None
        assert parse_history_timestamp(None) is None
        naive = parse_history_timestamp("2026-07-02T12:00:00")
        assert naive is not None and naive.tzinfo is not None


class TestLingarrMatching:
    def test_episode_matches_on_title_and_pair(self) -> None:
        records = [_request(), _request(request_id=2, title="Other Show")]
        evidence = lingarr_evidence_for_episode(
            records,
            display_title="Alpha Show",
            source_language="en",
            target_language="da",
        )
        assert [m.request_id for m in evidence.matches] == [1]
        assert evidence.any_active

    def test_two_episodes_of_one_show_share_the_same_match_set(self) -> None:
        # §6.5: the record carries show title + pair only, so lookups for two
        # different episodes of the same show both claim it.
        records = [_request()]
        for _ in range(2):
            evidence = lingarr_evidence_for_episode(
                records,
                display_title="Alpha Show",
                source_language="en",
                target_language="da",
            )
            assert len(evidence.matches) == 1

    def test_code2_conversion_cases_match(self) -> None:
        # Bazarr sends zh-CN/zh-TW/pt-BR to Lingarr (§6.3); intents hold code2.
        records = [_request(source="zh-CN", target="pt-BR")]
        evidence = lingarr_evidence_for_episode(
            records,
            display_title="Alpha Show",
            source_language="zh",
            target_language="pb",
        )
        assert len(evidence.matches) == 1

    def test_inactive_statuses_are_matched_but_not_active(self) -> None:
        records = [_request(status="Completed")]
        evidence = lingarr_evidence_for_episode(
            records,
            display_title="Alpha Show",
            source_language="en",
            target_language="da",
        )
        assert len(evidence.matches) == 1
        assert not evidence.any_active

    def test_movie_requires_exact_radarr_id_when_resolved(self) -> None:
        records = [
            _request(media_id=7, title="Alpha Movie", media_type="Movie"),
            _request(request_id=2, media_id=8, title="Alpha Movie", media_type="Movie"),
            _request(
                request_id=3, media_id=None, title="Alpha Movie", media_type="Movie"
            ),
        ]
        evidence = lingarr_evidence_for_movie(
            records,
            radarr_id=7,
            display_title="Alpha Movie",
            source_language="en",
            target_language="da",
        )
        assert sorted(m.request_id for m in evidence.matches) == [1, 3]

    def test_media_type_separation(self) -> None:
        records = [_request(media_type="Movie", title="Alpha Show")]
        evidence = lingarr_evidence_for_episode(
            records,
            display_title="Alpha Show",
            source_language="en",
            target_language="da",
        )
        assert evidence.matches == ()


class TestClassification:
    def test_file_backed_with_action_6_supersedes_via_translation(self) -> None:
        outcome = classify_backlog(
            SubtitlePresence(present=True, file_backed=True),
            HistoryEvidence(translated=True),
        )
        assert isinstance(outcome, Supersede)
        assert outcome.via_translation

    def test_file_backed_without_history_supersedes_by_other_means(self) -> None:
        outcome = classify_backlog(
            SubtitlePresence(present=True, file_backed=True),
            HistoryEvidence(translated=False),
        )
        assert isinstance(outcome, Supersede)
        assert not outcome.via_translation

    def test_embedded_only_never_supersedes(self) -> None:
        # A policy with skip_embedded_target=False deliberately wants a real
        # file; the embedded track existing is not goal attainment.
        outcome = classify_backlog(
            SubtitlePresence(present=True, embedded_only=True), None
        )
        assert isinstance(outcome, NoChange)

    def test_absent_is_no_change(self) -> None:
        assert isinstance(
            classify_backlog(SubtitlePresence(present=False), None), NoChange
        )
