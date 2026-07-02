"""Pure doctor-check tests with fabricated misconfiguration fixtures (P1-T6)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from perevoditarr.modules.doctor.checks import (
    CircuitBreakerStateCheck,
    ConcurrencyHeadroomCheck,
    LanguageCodeEdgeCasesCheck,
    LanguageProfilesCheck,
    LingarrAutomationCheck,
    LingarrServiceConfiguredCheck,
    OperationalSanityCheck,
    SubtitleValidationLimitsCheck,
    TelemetryStreamHealthCheck,
    TranslatorWiringCheck,
    TransportRetryBanCheck,
    UpgradeTranslatedCheck,
    VersionCapabilityReportCheck,
    all_checks,
)
from perevoditarr.modules.doctor.framework import (
    BazarrContext,
    DoctorContext,
    Finding,
    LingarrContext,
)
from perevoditarr.modules.integrations.bazarr.schemas import (
    GeneralSettings,
    LanguageProfileItem,
    LanguagesProfile,
    SystemSettings,
    TranslatorSettings,
)

_NOW = datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)


def _healthy_instance(**overrides: object) -> BazarrContext:
    base = BazarrContext(
        instance_id=uuid4(),
        name="main",
        url="http://bazarr.test",
        version="1.5.6",
        reachable=True,
        settings=SystemSettings(
            general=GeneralSettings(concurrent_jobs=4, upgrade_manual=True),
            translator=TranslatorSettings(
                translator_type="lingarr",
                lingarr_url="http://lingarr.test",
                lingarr_token="secret",
            ),
        ),
        profiles=[
            LanguagesProfile(
                profile_id=1,
                name="Default",
                items=[
                    LanguageProfileItem(id=1, language="en"),
                    LanguageProfileItem(id=2, language="da"),
                ],
            )
        ],
        lingarr=LingarrContext(
            instance_id=uuid4(),
            url="http://lingarr.test",
            version="1.2.4",
            reachable=True,
            settings={
                "automation_enabled": "false",
                "service_type": "libretranslate",
                "subtitle_validation_enabled": "true",
                "subtitle_validation_maxfilesizebytes": "2097152",
                "language_code_format": "",
            },
        ),
        mirror_synced_ever=True,
        last_sync_finished_at=_NOW - timedelta(hours=1),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _context(instance: BazarrContext, **kwargs: object) -> DoctorContext:
    forward_auth = bool(kwargs.get("forward_auth_misconfigured", False))
    return DoctorContext(
        now=_NOW, instances=[instance], forward_auth_misconfigured=forward_auth
    )


def _severities(findings: list[Finding]) -> list[str]:
    return [f.severity for f in findings]


class TestHealthyBaseline:
    def test_no_critical_findings_on_healthy_context(self) -> None:
        context = _context(_healthy_instance())
        for check in all_checks():
            for finding in check.run(context):
                assert finding.severity != "critical", (
                    f"{finding.check_id}: {finding.message}"
                )


class TestTranslatorWiring:
    def test_wrong_translator_type_is_critical(self) -> None:
        instance = _healthy_instance()
        instance.settings = SystemSettings(
            general=GeneralSettings(concurrent_jobs=4, upgrade_manual=True),
            translator=TranslatorSettings(translator_type="google_translate"),
        )
        findings = TranslatorWiringCheck().run(_context(instance))
        assert "critical" in _severities(list(findings))
        assert "not 'lingarr'" in findings[0].message

    def test_unreachable_bazarr_is_critical(self) -> None:
        instance = _healthy_instance()
        instance.reachable = False
        instance.settings = None
        findings = TranslatorWiringCheck().run(_context(instance))
        assert _severities(list(findings)) == ["critical"]

    def test_missing_token_warns(self) -> None:
        instance = _healthy_instance()
        instance.settings = SystemSettings(
            general=GeneralSettings(concurrent_jobs=4, upgrade_manual=True),
            translator=TranslatorSettings(
                translator_type="lingarr",
                lingarr_url="http://lingarr.test",
                lingarr_token="",
            ),
        )
        findings = TranslatorWiringCheck().run(_context(instance))
        assert "warn" in _severities(list(findings))


class TestLingarrAutomation:
    def test_automation_enabled_is_critical(self) -> None:
        instance = _healthy_instance()
        assert instance.lingarr is not None
        instance.lingarr.settings["automation_enabled"] = "true"
        findings = LingarrAutomationCheck().run(_context(instance))
        assert _severities(list(findings)) == ["critical"]

    def test_automation_disabled_is_silent(self) -> None:
        findings = LingarrAutomationCheck().run(_context(_healthy_instance()))
        assert findings == []


class TestUpgradeSetting:
    def test_upgrade_manual_off_warns(self) -> None:
        instance = _healthy_instance()
        instance.settings = SystemSettings(
            general=GeneralSettings(concurrent_jobs=4, upgrade_manual=False),
            translator=TranslatorSettings(translator_type="lingarr"),
        )
        findings = UpgradeTranslatedCheck().run(_context(instance))
        assert _severities(list(findings)) == ["warn"]


class TestProfilesAndLanguages:
    def test_no_profiles_warns(self) -> None:
        instance = _healthy_instance()
        instance.profiles = []
        findings = LanguageProfilesCheck().run(_context(instance))
        assert _severities(list(findings)) == ["warn"]

    def test_inventory_recorded(self) -> None:
        findings = LanguageProfilesCheck().run(_context(_healthy_instance()))
        info = [f for f in findings if f.severity == "info"]
        assert info and info[0].data == {"languages": ["da", "en"]}

    def test_code_conversion_edge_cases(self) -> None:
        instance = _healthy_instance()
        instance.profiles[0].items.append(LanguageProfileItem(id=3, language="zh"))
        findings = LanguageCodeEdgeCasesCheck().run(_context(instance))
        assert len(findings) == 1
        assert findings[0].data is not None
        assert findings[0].data["conversions"] == {"zh": "zh-CN"}


class TestLingarrService:
    def test_missing_service_type_is_critical(self) -> None:
        instance = _healthy_instance()
        assert instance.lingarr is not None
        instance.lingarr.settings["service_type"] = ""
        findings = LingarrServiceConfiguredCheck().run(_context(instance))
        assert _severities(list(findings)) == ["critical"]


class TestValidationLimits:
    def test_tiny_max_file_size_warns(self) -> None:
        instance = _healthy_instance()
        assert instance.lingarr is not None
        instance.lingarr.settings["subtitle_validation_maxfilesizebytes"] = "10000"
        findings = SubtitleValidationLimitsCheck().run(_context(instance))
        assert _severities(list(findings)) == ["warn"]


class TestConcurrencyHeadroom:
    def test_low_concurrent_jobs_warns(self) -> None:
        instance = _healthy_instance()
        instance.settings = SystemSettings(
            general=GeneralSettings(concurrent_jobs=2, upgrade_manual=True),
            translator=TranslatorSettings(translator_type="lingarr"),
        )
        findings = ConcurrencyHeadroomCheck().run(_context(instance))
        assert _severities(list(findings)) == ["warn"]


class TestTransportRetryBan:
    def test_real_transport_passes_self_check(self) -> None:
        findings = TransportRetryBanCheck().run(_context(_healthy_instance()))
        assert _severities(list(findings)) == ["info"]


class TestVersionReport:
    def test_always_reports_versions_and_capabilities(self) -> None:
        findings = VersionCapabilityReportCheck().run(_context(_healthy_instance()))
        assert len(findings) == 1
        assert findings[0].data is not None
        assert findings[0].data["bazarrVersion"] == "1.5.6"
        assert findings[0].data["translateReturnsJobId"] is False


class TestOperationalSanity:
    def test_never_synced_warns(self) -> None:
        instance = _healthy_instance()
        instance.mirror_synced_ever = False
        instance.last_sync_finished_at = None
        findings = OperationalSanityCheck().run(_context(instance))
        assert _severities(list(findings)) == ["warn"]
        assert "never" in findings[0].message

    def test_stale_mirror_warns(self) -> None:
        instance = _healthy_instance()
        instance.last_sync_finished_at = _NOW - timedelta(hours=30)
        findings = OperationalSanityCheck().run(_context(instance))
        assert _severities(list(findings)) == ["warn"]
        assert "stale" in findings[0].message

    def test_forward_auth_misconfiguration_is_critical(self) -> None:
        context = _context(_healthy_instance(), forward_auth_misconfigured=True)
        findings = OperationalSanityCheck().run(context)
        assert "critical" in _severities(list(findings))


def test_headroom_uses_effective_window_k() -> None:
    # concurrent_jobs=4 with the default K=2 leaves headroom — no finding.
    healthy = _context(_healthy_instance())
    assert ConcurrencyHeadroomCheck().run(healthy) == []
    # A per-instance override of K=4 removes the headroom → warn.
    no_headroom = _context(_healthy_instance(dispatch_window_k=4))
    findings = ConcurrencyHeadroomCheck().run(no_headroom)
    assert _severities(findings) == ["warn"]
    assert findings[0].data == {"concurrentJobs": 4, "dispatchWindow": 4}


def test_breaker_surfacing() -> None:
    assert CircuitBreakerStateCheck().run(_context(_healthy_instance())) == []
    open_ctx = _context(
        _healthy_instance(breaker_state="open", breaker_consecutive_failures=5)
    )
    findings = CircuitBreakerStateCheck().run(open_ctx)
    assert _severities(findings) == ["warn"]
    assert findings[0].data == {"breakerState": "open", "consecutiveFailures": 5}


def test_telemetry_stream_health_surfacing() -> None:
    assert TelemetryStreamHealthCheck().run(_context(_healthy_instance())) == []
    degraded = _context(
        _healthy_instance(telemetry_streams={"bazarr_socketio": "degraded"})
    )
    findings = TelemetryStreamHealthCheck().run(degraded)
    assert _severities(findings) == ["info"]
    assert findings[0].data == {"streams": ["bazarr_socketio"]}


def test_registry_contains_all_checks() -> None:
    # FR-DR1..FR-DR11 (P1-T6) plus P3 additions: circuit-breaker surfacing
    # (FR-DR12) and telemetry stream health (FR-DR13).
    ids = sorted(check.check_id for check in all_checks())
    assert ids == sorted(f"FR-DR{n}" for n in range(1, 14))
