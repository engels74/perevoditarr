"""Policy validation unit tests (P2-T1, FR-P4): §6.3 code conversions,
Bazarr/Lingarr inventory checks, Lingarr settings parsing."""

import pytest

from perevoditarr.modules.policy import (
    LanguageInventory,
    PolicyValues,
    convert_code2,
    parse_lingarr_language_setting,
    validate_profile_values,
)


@pytest.mark.parametrize(
    ("code2", "converted"),
    [("zh", "zh-CN"), ("zt", "zh-TW"), ("pb", "pt-BR"), ("en", "en"), ("da", "da")],
)
def test_convert_code2(code2: str, converted: str) -> None:
    assert convert_code2(code2) == converted


def test_parse_lingarr_language_setting_object_array() -> None:
    raw = '[{"code":"en","name":"English"},{"code":"da","name":"Danish"}]'
    assert parse_lingarr_language_setting(raw) == frozenset({"en", "da"})


def test_parse_lingarr_language_setting_string_array_and_garbage() -> None:
    assert parse_lingarr_language_setting('["en","da"]') == frozenset({"en", "da"})
    assert parse_lingarr_language_setting("not json") is None
    assert parse_lingarr_language_setting('{"code":"en"}') is None
    assert parse_lingarr_language_setting("") is None
    assert parse_lingarr_language_setting(None) is None


_BAZARR_LANGS = frozenset({"en", "da"})
_LINGARR_SOURCES = frozenset({"en"})
_LINGARR_TARGETS = frozenset({"da"})


def _inventory(
    *,
    bazarr: frozenset[str] | None = _BAZARR_LANGS,
    sources: frozenset[str] | None = _LINGARR_SOURCES,
    targets: frozenset[str] | None = _LINGARR_TARGETS,
) -> LanguageInventory:
    return LanguageInventory(
        instance_name="main",
        bazarr_languages=bazarr,
        lingarr_sources=sources,
        lingarr_targets=targets,
    )


def test_clean_profile_produces_no_warnings() -> None:
    values = PolicyValues(target_languages=["da"], source_preferences=["en"])
    findings = validate_profile_values(values, (_inventory(),))
    assert findings == []


def test_target_missing_from_bazarr_profiles_warns() -> None:
    values = PolicyValues(target_languages=["sv"], source_preferences=["en"])
    findings = validate_profile_values(
        values, (_inventory(targets=frozenset({"sv", "da"})),)
    )
    assert "target-not-wanted" in [f.code for f in findings]


def test_unreachable_instance_degrades_to_info() -> None:
    values = PolicyValues(target_languages=["da"])
    findings = validate_profile_values(
        values, (_inventory(bazarr=None, sources=None, targets=None),)
    )
    assert [f.code for f in findings] == ["inventory-unavailable"]
    assert findings[0].severity == "info"


def test_pair_not_in_lingarr_languages_warns() -> None:
    values = PolicyValues(target_languages=["da"], source_preferences=["de"])
    findings = validate_profile_values(values, (_inventory(),))
    assert "source-not-in-lingarr" in [f.code for f in findings]


def test_code2_conversion_cases_accept_converted_lingarr_codes() -> None:
    # Lingarr configured with the *converted* codes: zh-CN as target.
    values = PolicyValues(target_languages=["zh"], source_preferences=["en"])
    findings = validate_profile_values(
        values,
        (
            _inventory(
                bazarr=frozenset({"en", "zh"}),
                targets=frozenset({"zh-CN"}),
            ),
        ),
    )
    assert "target-not-in-lingarr" not in [f.code for f in findings]
    assert "code2-conversion" in [f.code for f in findings]


def test_code2_conversion_cases_flag_missing_converted_codes() -> None:
    values = PolicyValues(target_languages=["pb"], source_preferences=["en"])
    findings = validate_profile_values(
        values,
        (
            _inventory(
                bazarr=frozenset({"en", "pb"}),
                targets=frozenset({"da"}),  # neither pb nor pt-BR
            ),
        ),
    )
    assert "target-not-in-lingarr" in [f.code for f in findings]


def test_source_equals_target_is_critical() -> None:
    values = PolicyValues(target_languages=["en"], source_preferences=["en"])
    findings = validate_profile_values(values, ())
    critical = [f for f in findings if f.code == "source-equals-target"]
    assert len(critical) == 1
    assert critical[0].severity == "critical"


def test_empty_target_list_and_duplicates_warn() -> None:
    empty = validate_profile_values(PolicyValues(target_languages=[]), ())
    assert "no-targets" in [f.code for f in empty]
    duplicated = validate_profile_values(
        PolicyValues(target_languages=["da", "da"]), ()
    )
    assert "duplicate-target" in [f.code for f in duplicated]


def test_duplicate_source_preferences_warn() -> None:
    findings = validate_profile_values(
        PolicyValues(target_languages=["da"], source_preferences=["en", "en"]), ()
    )
    assert "duplicate-source" in [f.code for f in findings]


def test_source_equals_target_after_code2_conversion_is_critical() -> None:
    # `zh` converts to `zh-CN` on the wire (§6.3): a profile targeting
    # `zh-CN` with source `zh` is self-translation despite raw inequality.
    findings = validate_profile_values(
        PolicyValues(target_languages=["zh-CN"], source_preferences=["zh"]), ()
    )
    critical = [f for f in findings if f.code == "source-equals-target"]
    assert len(critical) == 1
    assert critical[0].severity == "critical"
    assert "zh-CN" in critical[0].message
