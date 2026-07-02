"""FR-DR4/FR-DR6 doctor checks against translation profiles (P2-T1 wiring)."""

from datetime import UTC, datetime
from uuid import uuid4

from perevoditarr.modules.doctor.checks import (
    LanguageCodeEdgeCasesCheck,
    LanguageProfilesCheck,
)
from perevoditarr.modules.doctor.framework import (
    BazarrContext,
    DoctorContext,
    LingarrContext,
)
from perevoditarr.modules.integrations.bazarr.schemas import (
    LanguageProfileItem,
    LanguagesProfile,
)
from perevoditarr.modules.policy import PolicyValues, ProfilePolicySummary

INSTANCE_ID = uuid4()


def _bazarr(languages: list[str]) -> BazarrContext:
    profile = LanguagesProfile(
        profile_id=1,
        name="default",
        items=[
            LanguageProfileItem(id=i, language=lang) for i, lang in enumerate(languages)
        ],
    )
    return BazarrContext(
        instance_id=INSTANCE_ID,
        name="main",
        url="http://bazarr",
        reachable=True,
        profiles=[profile],
        lingarr=LingarrContext(
            instance_id=uuid4(),
            reachable=True,
            settings={
                "source_languages": '[{"code":"en","name":"English"}]',
                "target_languages": '[{"code":"da","name":"Danish"}]',
                "language_code_format": "",
            },
        ),
    )


def _context(
    languages: list[str], summaries: list[ProfilePolicySummary]
) -> DoctorContext:
    return DoctorContext(
        now=datetime.now(UTC),
        instances=[_bazarr(languages)],
        translation_profiles=summaries,
    )


def _summary(values: PolicyValues) -> ProfilePolicySummary:
    return ProfilePolicySummary(
        profile_id=uuid4(),
        name="Anime",
        values=values,
        instance_ids=(INSTANCE_ID,),
    )


def test_dr4_flags_profile_target_missing_from_bazarr_languages() -> None:
    context = _context(["en", "da"], [_summary(PolicyValues(target_languages=["sv"]))])
    findings = LanguageProfilesCheck().run(context)
    profile_warnings = [
        f for f in findings if f.severity == "warn" and "Anime" in f.message
    ]
    assert len(profile_warnings) == 1
    assert "sv" in profile_warnings[0].message


def test_dr4_quiet_when_profile_targets_are_wanted() -> None:
    context = _context(["en", "da"], [_summary(PolicyValues(target_languages=["da"]))])
    findings = LanguageProfilesCheck().run(context)
    assert not [f for f in findings if "Anime" in f.message]


def test_dr4_ignores_profiles_not_assigned_to_the_instance() -> None:
    unassigned = ProfilePolicySummary(
        profile_id=uuid4(),
        name="Anime",
        values=PolicyValues(target_languages=["sv"]),
        instance_ids=(),
    )
    findings = LanguageProfilesCheck().run(_context(["en", "da"], [unassigned]))
    assert not [f for f in findings if "Anime" in f.message]


def test_dr6_flags_pairs_outside_lingarr_languages() -> None:
    context = _context(
        ["en", "da", "sv"],
        [_summary(PolicyValues(target_languages=["sv"], source_preferences=["en"]))],
    )
    findings = LanguageCodeEdgeCasesCheck().run(context)
    pair_warnings = [f for f in findings if "Anime" in f.message]
    assert len(pair_warnings) == 1
    assert "sv" in pair_warnings[0].message


def test_dr6_accepts_converted_code2_in_lingarr_lists() -> None:
    context = DoctorContext(
        now=datetime.now(UTC),
        instances=[_bazarr(["en", "zh"])],
        translation_profiles=[
            _summary(PolicyValues(target_languages=["zh"], source_preferences=["en"]))
        ],
    )
    # Lingarr knows the converted code (§6.3): zh-CN.
    context.instances[0].lingarr = LingarrContext(
        instance_id=uuid4(),
        reachable=True,
        settings={
            "source_languages": '[{"code":"en"}]',
            "target_languages": '[{"code":"zh-CN"}]',
            "language_code_format": "",
        },
    )
    findings = LanguageCodeEdgeCasesCheck().run(context)
    assert not [f for f in findings if "Anime" in f.message and f.severity == "warn"]
    # The §6.3 conversion notice for the instance's own zh profile remains.
    assert [f for f in findings if "zh→zh-CN" in f.message]
