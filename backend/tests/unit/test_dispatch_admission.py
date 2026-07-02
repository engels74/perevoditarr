"""Pure dispatcher admission helpers (P3-T2): the headroom window and source
subtitle election."""

from perevoditarr.modules.dispatch.dispatcher import elect_source_path, headroom_window
from perevoditarr.modules.integrations.bazarr.schemas import SubtitleFile


def test_headroom_unbounded_when_concurrency_unknown() -> None:
    assert headroom_window(2, None) == 2


def test_headroom_leaves_a_slot_below_concurrent_jobs() -> None:
    assert headroom_window(2, 4) == 2  # min(2, 3)
    assert headroom_window(5, 4) == 3  # capped by concurrent_jobs - 1
    assert headroom_window(2, 2) == 1  # one slot of headroom


def test_headroom_never_drops_below_one() -> None:
    assert headroom_window(2, 1) == 1


def test_elect_source_prefers_plain_track() -> None:
    subtitles = [
        SubtitleFile(code2="en", path="/x/en.forced.srt", forced=True),
        SubtitleFile(code2="en", path="/x/en.srt"),
    ]
    assert elect_source_path(subtitles, "en") == "/x/en.srt"


def test_elect_source_falls_back_to_any_file_backed() -> None:
    subtitles = [SubtitleFile(code2="en", path="/x/en.hi.srt", hi=True)]
    assert elect_source_path(subtitles, "en") == "/x/en.hi.srt"


def test_elect_source_ignores_embedded_and_other_languages() -> None:
    subtitles = [
        SubtitleFile(code2="en", path=None),  # embedded — unusable
        SubtitleFile(code2="de", path="/x/de.srt"),  # wrong language
    ]
    assert elect_source_path(subtitles, "en") is None
