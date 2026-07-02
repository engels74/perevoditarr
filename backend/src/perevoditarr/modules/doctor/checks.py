"""FR-DR1..FR-DR11 checks (P1-T6). Each yields explained, guided findings."""

from datetime import timedelta

from perevoditarr.core.http import build_transport
from perevoditarr.modules.doctor.framework import (
    BazarrContext,
    DoctorCheck,
    DoctorContext,
    Finding,
    Severity,
    register,
    registered_checks,
)
from perevoditarr.modules.policy import (
    CODE2_CONVERSIONS,
    LanguageInventory,
    ProfilePolicySummary,
    parse_lingarr_language_setting,
    validate_profile_values,
)

# §6.3: Bazarr converts these before calling Lingarr (single-sourced in policy).
_CODE_CONVERSIONS = CODE2_CONVERSIONS


def _assigned_profiles(
    context: DoctorContext, instance: BazarrContext
) -> list[ProfilePolicySummary]:
    return [
        summary
        for summary in context.translation_profiles
        if instance.instance_id in summary.instance_ids
    ]


def _instance_inventory(instance: BazarrContext) -> LanguageInventory:
    """LanguageInventory for one Bazarr+Lingarr pair from doctor context data."""
    lingarr = instance.lingarr
    return LanguageInventory(
        instance_name=instance.name,
        bazarr_languages=(
            frozenset(_profile_languages(instance)) if instance.reachable else None
        ),
        lingarr_sources=(
            parse_lingarr_language_setting(lingarr.settings.get("source_languages"))
            if lingarr is not None and lingarr.reachable
            else None
        ),
        lingarr_targets=(
            parse_lingarr_language_setting(lingarr.settings.get("target_languages"))
            if lingarr is not None and lingarr.reachable
            else None
        ),
    )


_STALE_MIRROR_AGE = timedelta(hours=24)


def _profile_languages(instance: BazarrContext) -> list[str]:
    return [
        item.language
        for profile in instance.profiles
        for item in profile.items
        if item.language
    ]


@register
class TranslatorWiringCheck:
    """FR-DR1: Bazarr must delegate translation to a reachable Lingarr."""

    check_id: str = "FR-DR1"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            if not instance.reachable or instance.settings is None:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="critical",
                        message=f"Bazarr '{instance.name}' is unreachable",
                        explanation=(
                            "Perevoditarr cannot read this Bazarr instance's "
                            "settings, so the translation wiring cannot be verified."
                        ),
                        fix_guidance=(
                            "Check the instance URL and API key, and that Bazarr "
                            "is running and reachable from Perevoditarr."
                        ),
                        bazarr_instance_id=instance.instance_id,
                    )
                )
                continue
            translator = instance.settings.translator
            translator_type = translator.translator_type if translator else None
            if translator_type != "lingarr":
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="critical",
                        message=(
                            f"Bazarr '{instance.name}' translator is "
                            f"'{translator_type or 'unset'}', not 'lingarr'"
                        ),
                        explanation=(
                            "Translations requested through Bazarr will not go "
                            "to Lingarr, so Perevoditarr's dispatches would use "
                            "a different (possibly paid) translator."
                        ),
                        fix_guidance=(
                            "In Bazarr: Settings → Subtitles → Translating, set "
                            "the translator to Lingarr and fill in its URL/token."
                        ),
                        bazarr_instance_id=instance.instance_id,
                    )
                )
                continue
            if translator is None or not translator.lingarr_url:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="critical",
                        message=f"Bazarr '{instance.name}' has no Lingarr URL set",
                        explanation="Translate requests would fail immediately.",
                        fix_guidance=(
                            "Set the Lingarr URL in Bazarr's translating settings."
                        ),
                        bazarr_instance_id=instance.instance_id,
                    )
                )
                continue
            if not translator.lingarr_token:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="warn",
                        message=(f"Bazarr '{instance.name}' has no Lingarr API token"),
                        explanation=(
                            "If Lingarr has authentication enabled, Bazarr's "
                            "translate calls will be rejected with 401."
                        ),
                        fix_guidance=(
                            "Copy Lingarr's API key into Bazarr's translating "
                            "settings (or confirm Lingarr auth is disabled)."
                        ),
                        bazarr_instance_id=instance.instance_id,
                    )
                )
            if instance.lingarr is not None and not instance.lingarr.reachable:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="critical",
                        message=(
                            f"Lingarr for Bazarr '{instance.name}' is unreachable "
                            "from Perevoditarr"
                        ),
                        explanation=(
                            "Perevoditarr cannot observe translation requests, "
                            "so convergence evidence and the doctor's Lingarr "
                            "checks are blind."
                        ),
                        fix_guidance=(
                            "Check the Lingarr URL/API key registered in "
                            "Perevoditarr and Lingarr's availability."
                        ),
                        bazarr_instance_id=instance.instance_id,
                        lingarr_instance_id=instance.lingarr.instance_id,
                    )
                )
        return findings


@register
class LingarrAutomationCheck:
    """FR-DR2: Lingarr's own automation must be off (PRD §6.7)."""

    check_id: str = "FR-DR2"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            lingarr = instance.lingarr
            if lingarr is None or not lingarr.reachable:
                continue
            if lingarr.settings.get("automation_enabled") == "true":
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="critical",
                        message="Lingarr automation_enabled is ON",
                        explanation=(
                            "Lingarr's own automation translates files directly "
                            "and invisibly to Bazarr: double work, wasted spend, "
                            "and §6.4 dedup collisions with Perevoditarr traffic."
                        ),
                        fix_guidance=(
                            "Disable automation in Lingarr (Settings → "
                            "Automation) and let Perevoditarr drive translation "
                            "through Bazarr."
                        ),
                        bazarr_instance_id=instance.instance_id,
                        lingarr_instance_id=lingarr.instance_id,
                    )
                )
        return findings


@register
class UpgradeTranslatedCheck:
    """FR-DR3: 'Upgrade Manually Downloaded or Translated Subtitles' on."""

    check_id: str = "FR-DR3"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            general = instance.settings.general if instance.settings else None
            if general is None or general.upgrade_manual is None:
                continue
            if general.upgrade_manual is False:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="warn",
                        message=(
                            f"Bazarr '{instance.name}' will never upgrade "
                            "translated subtitles"
                        ),
                        explanation=(
                            "With upgrade_manual off, machine-translated "
                            "subtitles are dead ends: Bazarr will not replace "
                            "them when a real subtitle appears."
                        ),
                        fix_guidance=(
                            "Enable 'Upgrade Manually Downloaded or Translated "
                            "Subtitles' in Bazarr's subtitle settings."
                        ),
                        bazarr_instance_id=instance.instance_id,
                    )
                )
        return findings


@register
class LanguageProfilesCheck:
    """FR-DR4: language profiles exist and carry languages (policy foundation)."""

    check_id: str = "FR-DR4"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            if not instance.reachable:
                continue
            if not instance.profiles:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="warn",
                        message=(f"Bazarr '{instance.name}' has no language profiles"),
                        explanation=(
                            "Without language profiles nothing is ever 'wanted', "
                            "so no translation targets can be discovered."
                        ),
                        fix_guidance=(
                            "Create a language profile in Bazarr and assign it "
                            "to your libraries."
                        ),
                        bazarr_instance_id=instance.instance_id,
                    )
                )
                continue
            empty = [p.name for p in instance.profiles if not p.items]
            if empty:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="warn",
                        message=(
                            f"Bazarr '{instance.name}' has empty language "
                            f"profiles: {', '.join(empty)}"
                        ),
                        explanation="Profiles without languages never want anything.",
                        fix_guidance="Add languages to the profile or remove it.",
                        bazarr_instance_id=instance.instance_id,
                    )
                )
            findings.append(
                Finding(
                    check_id=self.check_id,
                    severity="info",
                    message=(f"Bazarr '{instance.name}' language inventory recorded"),
                    explanation=(
                        "Translation-profile targets are validated against this "
                        "inventory when policies land (FR-P4)."
                    ),
                    fix_guidance="No action needed.",
                    bazarr_instance_id=instance.instance_id,
                    data={"languages": sorted(set(_profile_languages(instance)))},
                )
            )
            # P2-T1 wiring: profile targets vs this instance's inventory (FR-P4).
            inventory = _instance_inventory(instance)
            for summary in _assigned_profiles(context, instance):
                for finding in validate_profile_values(summary.values, (inventory,)):
                    if finding.code != "target-not-wanted":
                        continue
                    findings.append(
                        Finding(
                            check_id=self.check_id,
                            severity="warn",
                            message=(f"Profile '{summary.name}': {finding.message}"),
                            explanation=(
                                "Targets outside Bazarr's language profiles are "
                                "never 'wanted', so this profile target can "
                                "never be discovered on this instance."
                            ),
                            fix_guidance=finding.fix_guidance,
                            bazarr_instance_id=instance.instance_id,
                            data={"profileId": str(summary.profile_id)},
                        )
                    )
        return findings


@register
class LingarrServiceConfiguredCheck:
    """FR-DR5: Lingarr translation service is configured."""

    check_id: str = "FR-DR5"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            lingarr = instance.lingarr
            if lingarr is None or not lingarr.reachable:
                continue
            if not lingarr.settings.get("service_type"):
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="critical",
                        message="Lingarr has no translation service configured",
                        explanation=(
                            "Every translate call will fail until a service "
                            "(LibreTranslate, DeepL, OpenAI, ...) is selected."
                        ),
                        fix_guidance=(
                            "Configure a translation service in Lingarr, "
                            "including credentials."
                        ),
                        bazarr_instance_id=instance.instance_id,
                        lingarr_instance_id=lingarr.instance_id,
                    )
                )
        return findings


@register
class LanguageCodeEdgeCasesCheck:
    """FR-DR6: zh/zt/pb code conversions (§6.3) vs Lingarr code format."""

    check_id: str = "FR-DR6"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            affected = sorted(
                {
                    lang
                    for lang in _profile_languages(instance)
                    if lang in _CODE_CONVERSIONS
                }
            )
            lingarr = instance.lingarr
            code_format = (
                lingarr.settings.get("language_code_format", "") if lingarr else ""
            )
            if affected:
                conversions = {lang: _CODE_CONVERSIONS[lang] for lang in affected}
                severity: Severity = "warn" if code_format else "info"
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity=severity,
                        message=(
                            f"Language-code conversions apply on '{instance.name}': "
                            + ", ".join(f"{a}→{b}" for a, b in conversions.items())
                        ),
                        explanation=(
                            "Bazarr converts these codes before calling Lingarr "
                            "(§6.3). If Lingarr's language_code_format disagrees, "
                            "pairs may not match its configured languages."
                        ),
                        fix_guidance=(
                            "Verify Lingarr's source/target languages include the "
                            "converted codes; review language_code_format if set."
                        ),
                        bazarr_instance_id=instance.instance_id,
                        data={
                            "conversions": dict(conversions),
                            "languageCodeFormat": code_format,
                        },
                    )
                )
            # P2-T1 wiring: profile pairs vs Lingarr's configured languages,
            # honoring §6.3 conversions (FR-P4).
            inventory = _instance_inventory(instance)
            for summary in _assigned_profiles(context, instance):
                for finding in validate_profile_values(summary.values, (inventory,)):
                    if finding.code not in (
                        "target-not-in-lingarr",
                        "source-not-in-lingarr",
                    ):
                        continue
                    findings.append(
                        Finding(
                            check_id=self.check_id,
                            severity="warn",
                            message=f"Profile '{summary.name}': {finding.message}",
                            explanation=(
                                "Pairs outside Lingarr's configured "
                                "source/target languages fail at translation "
                                "time (§6.7 — Lingarr's settings are "
                                "authoritative)."
                            ),
                            fix_guidance=finding.fix_guidance,
                            bazarr_instance_id=instance.instance_id,
                            lingarr_instance_id=(
                                lingarr.instance_id if lingarr else None
                            ),
                            data={"profileId": str(summary.profile_id)},
                        )
                    )
        return findings


@register
class SubtitleValidationLimitsCheck:
    """FR-DR7: Lingarr validation limits vs likely traffic."""

    check_id: str = "FR-DR7"

    _MIN_REASONABLE_FILE_SIZE: int = 1_048_576  # 1 MiB

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            lingarr = instance.lingarr
            if lingarr is None or not lingarr.reachable:
                continue
            if lingarr.settings.get("subtitle_validation_enabled") != "true":
                continue
            raw = lingarr.settings.get("subtitle_validation_maxfilesizebytes", "")
            if raw.isdigit() and int(raw) < self._MIN_REASONABLE_FILE_SIZE:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="warn",
                        message=(f"Lingarr max subtitle file size is {raw} bytes"),
                        explanation=(
                            "Subtitles for long content routinely exceed this; "
                            "Lingarr would reject them and translations would "
                            "fail as poison-looking errors."
                        ),
                        fix_guidance=(
                            "Raise subtitle_validation_maxfilesizebytes in "
                            "Lingarr (≥ 1 MiB is typical)."
                        ),
                        bazarr_instance_id=instance.instance_id,
                        lingarr_instance_id=lingarr.instance_id,
                    )
                )
        return findings


@register
class ConcurrencyHeadroomCheck:
    """FR-DR8 (live, P3-T6): Bazarr concurrent_jobs vs the *effective* dispatch
    window K (per-instance override or active-preset default)."""

    check_id: str = "FR-DR8"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            general = instance.settings.general if instance.settings else None
            if general is None or general.concurrent_jobs is None:
                continue
            window_k = instance.dispatch_window_k
            if general.concurrent_jobs <= window_k:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="warn",
                        message=(
                            f"Bazarr '{instance.name}' concurrent_jobs="
                            f"{general.concurrent_jobs} leaves no headroom over "
                            f"the dispatch window (K={window_k})"
                        ),
                        explanation=(
                            "Bazarr's queue is shared with syncs and searches "
                            "(§6.2); translation dispatches could monopolize it. "
                            "The dispatcher leaves one slot below concurrent_jobs "
                            "(§7.2), so K must stay under it."
                        ),
                        fix_guidance=(
                            "Raise concurrent_jobs in Bazarr, or lower "
                            "Perevoditarr's dispatch window K for this instance."
                        ),
                        bazarr_instance_id=instance.instance_id,
                        data={
                            "concurrentJobs": general.concurrent_jobs,
                            "dispatchWindow": window_k,
                        },
                    )
                )
        return findings


@register
class CircuitBreakerStateCheck:
    """P3-T6: surface an open/half-open provider circuit breaker (§7.4)."""

    check_id: str = "FR-DR12"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            if instance.breaker_state == "closed":
                continue
            findings.append(
                Finding(
                    check_id=self.check_id,
                    severity="warn",
                    message=(
                        f"Circuit breaker is {instance.breaker_state} for "
                        f"'{instance.name}' after "
                        f"{instance.breaker_consecutive_failures} consecutive "
                        "provider failures"
                    ),
                    explanation=(
                        "Dispatch to this instance is paused while Lingarr/the "
                        "provider appears unhealthy (§7.4); it probes for recovery "
                        "and auto-closes on success."
                    ),
                    fix_guidance=(
                        "Check Lingarr and its translation provider (quota, "
                        "connectivity). Dispatch resumes automatically once a "
                        "probe succeeds."
                    ),
                    bazarr_instance_id=instance.instance_id,
                    data={
                        "breakerState": instance.breaker_state,
                        "consecutiveFailures": (instance.breaker_consecutive_failures),
                    },
                )
            )
        return findings


@register
class TelemetryStreamHealthCheck:
    """P3-T4/T6: surface telemetry streams running on the polling fallback."""

    check_id: str = "FR-DR13"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            degraded = sorted(
                stream
                for stream, state in instance.telemetry_streams.items()
                if state != "live"
            )
            if not degraded:
                continue
            findings.append(
                Finding(
                    check_id=self.check_id,
                    severity="info",
                    message=(
                        f"Telemetry for '{instance.name}' is on the polling "
                        f"fallback ({', '.join(degraded)})"
                    ),
                    explanation=(
                        "The websocket stream is unavailable (often a reverse "
                        "proxy blocking upgrades). Live UI still works via "
                        "polling (§7.3); this is graceful, not an error."
                    ),
                    fix_guidance=(
                        "To restore push updates, allow WebSocket upgrades to "
                        "Bazarr/Lingarr through any proxy in front of them."
                    ),
                    bazarr_instance_id=instance.instance_id,
                    data={"streams": degraded},
                )
            )
        return findings


@register
class TransportRetryBanCheck:
    """FR-DR9: Perevoditarr's own transport layer performs no retries."""

    check_id: str = "FR-DR9"

    def run(self, context: DoctorContext) -> list[Finding]:
        _ = context
        transport = build_transport()
        pool: object = transport._pool  # pyright: ignore[reportPrivateUsage]
        retries = getattr(pool, "_retries", None)
        if retries == 0:
            return [
                Finding(
                    check_id=self.check_id,
                    severity="info",
                    message="Transport-level retries are disabled (retries=0)",
                    explanation=(
                        "Bazarr already retries 3x toward Lingarr (§6.3); "
                        "intent-level retry is Perevoditarr's only retry surface."
                    ),
                    fix_guidance="No action needed.",
                )
            ]
        return [
            Finding(
                check_id=self.check_id,
                severity="critical",
                message=f"Transport retries are NOT disabled (retries={retries!r})",
                explanation=(
                    "Retry stacking multiplies provider calls up to 9x per "
                    "failure (§6.3 / FR-DR9)."
                ),
                fix_guidance=(
                    "This is a Perevoditarr build defect — report it upstream; "
                    "core/http.py must construct AsyncHTTPTransport(retries=0)."
                ),
            )
        ]


@register
class VersionCapabilityReportCheck:
    """FR-DR10: per-instance version & capability report."""

    check_id: str = "FR-DR10"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            capabilities = instance.capabilities
            findings.append(
                Finding(
                    check_id=self.check_id,
                    severity="info",
                    message=f"Version/capability report for '{instance.name}'",
                    explanation=(
                        "Capability slots stay False for every released "
                        "upstream pair (§6.6); they flip only when a future "
                        "Bazarr/Lingarr release improves the seam."
                    ),
                    fix_guidance="No action needed.",
                    bazarr_instance_id=instance.instance_id,
                    lingarr_instance_id=(
                        instance.lingarr.instance_id if instance.lingarr else None
                    ),
                    data={
                        "bazarrVersion": instance.version,
                        "lingarrVersion": (
                            instance.lingarr.version if instance.lingarr else None
                        ),
                        "translateReturnsJobId": (
                            capabilities.translate_returns_job_id
                            if capabilities
                            else False
                        ),
                        "lingarrReceivesEpisodeId": (
                            capabilities.lingarr_receives_episode_id
                            if capabilities
                            else False
                        ),
                    },
                )
            )
        return findings


@register
class OperationalSanityCheck:
    """FR-DR11: mirror freshness and auth configuration sanity."""

    check_id: str = "FR-DR11"

    def run(self, context: DoctorContext) -> list[Finding]:
        findings: list[Finding] = []
        for instance in context.instances:
            if not instance.mirror_synced_ever:
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="warn",
                        message=(
                            f"Library mirror for '{instance.name}' has never "
                            "completed a sync"
                        ),
                        explanation=(
                            "The UI and discovery read the mirror, never Bazarr "
                            "directly (FR-M1); without a sync they see nothing."
                        ),
                        fix_guidance="Run a full sync from the instance settings.",
                        bazarr_instance_id=instance.instance_id,
                    )
                )
            elif (
                instance.last_sync_finished_at is not None
                and context.now - instance.last_sync_finished_at > _STALE_MIRROR_AGE
            ):
                findings.append(
                    Finding(
                        check_id=self.check_id,
                        severity="warn",
                        message=f"Library mirror for '{instance.name}' is stale",
                        explanation=(
                            "The last completed sync is older than 24 hours; "
                            "browse data and wanted discovery are drifting."
                        ),
                        fix_guidance=(
                            "Check the sync scheduler and the instance's health."
                        ),
                        bazarr_instance_id=instance.instance_id,
                        data={
                            "lastSyncFinishedAt": (
                                instance.last_sync_finished_at.isoformat()
                            )
                        },
                    )
                )
        if context.forward_auth_misconfigured:
            findings.append(
                Finding(
                    check_id=self.check_id,
                    severity="critical",
                    message="Forward-auth is enabled without trusted proxies",
                    explanation=(
                        "Without a trusted-proxy allowlist, Remote-User headers "
                        "cannot be trusted; forward-auth refuses to authenticate "
                        "anyone in this state."
                    ),
                    fix_guidance=(
                        "Set PEREVODITARR_TRUSTED_PROXIES to your proxy's CIDR "
                        "or disable forward-auth."
                    ),
                )
            )
        return findings


def all_checks() -> tuple[DoctorCheck, ...]:
    """The FR-DR1..FR-DR11 registry (populated by this module's imports)."""
    return registered_checks()
