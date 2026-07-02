"""Policy validation (P2-T1, FR-P4): pure checks shared by the profile-editor
API responses and the doctor's FR-DR4/FR-DR6 checks.

Validates profile values against a Bazarr instance's language-profile
inventory and a Lingarr instance's configured source/target languages,
honoring the §6.3 code conversions (zh→zh-CN, zt→zh-TW, pb→pt-BR).
Soft findings are typed data, never exceptions — the editor shows them inline.
"""

from typing import Literal
from uuid import UUID

import msgspec

from perevoditarr.modules.policy.resolver import CODE2_CONVERSIONS, PolicyValues

type ValidationSeverity = Literal["info", "warn", "critical"]


class ProfilePolicySummary(msgspec.Struct, kw_only=True, frozen=True):
    """Plain snapshot of a translation profile for the doctor (FR-DR4/DR6)."""

    profile_id: UUID
    name: str
    values: PolicyValues
    instance_ids: tuple[UUID, ...] = ()


class PolicyFinding(msgspec.Struct, kw_only=True, frozen=True):
    code: str
    severity: ValidationSeverity
    message: str
    fix_guidance: str
    instance_name: str | None = None


class LanguageInventory(msgspec.Struct, kw_only=True, frozen=True):
    """What one Bazarr+Lingarr pair can want and translate."""

    instance_name: str
    # None = unknown (instance unreachable) — validation degrades to info.
    bazarr_languages: frozenset[str] | None = None
    lingarr_sources: frozenset[str] | None = None
    lingarr_targets: frozenset[str] | None = None


def convert_code2(code: str) -> str:
    """The wire code Lingarr actually receives for a Bazarr code2 (§6.3)."""
    return CODE2_CONVERSIONS.get(code, code)


def parse_lingarr_language_setting(raw: str | None) -> frozenset[str] | None:
    """Lingarr stores source/target languages as a JSON array of
    {code, name} objects; tolerate plain string arrays and garbage (None)."""
    if not raw:
        return None
    try:
        entries = msgspec.json.decode(raw, type=list[dict[str, object] | str])
    except msgspec.DecodeError:
        return None
    codes: set[str] = set()
    for entry in entries:
        if isinstance(entry, str):
            codes.add(entry)
        else:
            code = entry.get("code")
            if isinstance(code, str):
                codes.add(code)
    return frozenset(codes)


def _lingarr_knows(code: str, configured: frozenset[str]) -> bool:
    # Lingarr's language_code_format means either raw code2 or the converted
    # form may appear in its configured lists — accept either (§6.3/FR-DR6).
    return code in configured or convert_code2(code) in configured


def validate_profile_values(
    values: PolicyValues, inventories: tuple[LanguageInventory, ...]
) -> list[PolicyFinding]:
    findings: list[PolicyFinding] = []
    targets = values.target_languages or []
    sources = values.source_preferences or []

    if values.target_languages is not None and not targets:
        findings.append(
            PolicyFinding(
                code="no-targets",
                severity="warn",
                message="Profile sets an empty target-language list",
                fix_guidance="Add at least one target language or unset the field to inherit.",
            )
        )
    for duplicate in sorted({t for t in targets if targets.count(t) > 1}):
        findings.append(
            PolicyFinding(
                code="duplicate-target",
                severity="warn",
                message=f"Target language {duplicate!r} is listed more than once",
                fix_guidance="Remove the duplicate entry.",
            )
        )
    for duplicate in sorted({s for s in sources if sources.count(s) > 1}):
        findings.append(
            PolicyFinding(
                code="duplicate-source",
                severity="warn",
                message=f"Source preference {duplicate!r} is listed more than once",
                fix_guidance="Remove the duplicate entry.",
            )
        )
    for code in (t for t in targets if t in sources):
        findings.append(
            PolicyFinding(
                code="source-equals-target",
                severity="critical",
                message=f"{code!r} is both a source preference and a target",
                fix_guidance="A language cannot be translated into itself; remove it from one list.",
            )
        )
    # §6.3 conversion can make a raw-distinct pair collide on the wire
    # (e.g. source `zh` converts to `zh-CN` while `zh-CN` is a target).
    for target in targets:
        for source in sources:
            if source != target and convert_code2(source) == convert_code2(target):
                findings.append(
                    PolicyFinding(
                        code="source-equals-target",
                        severity="critical",
                        message=(
                            f"Source {source!r} and target {target!r} are the "
                            f"same language after §6.3 conversion "
                            f"({convert_code2(source)!r})"
                        ),
                        fix_guidance=(
                            "A language cannot be translated into itself; "
                            "remove it from one list."
                        ),
                    )
                )
    for code in (c for c in [*targets, *sources] if c in CODE2_CONVERSIONS):
        findings.append(
            PolicyFinding(
                code="code2-conversion",
                severity="info",
                message=(
                    f"Bazarr sends {code!r} to Lingarr as "
                    f"{convert_code2(code)!r} (§6.3)"
                ),
                fix_guidance=(
                    "Make sure Lingarr's language lists include the converted "
                    "code; the doctor cross-checks this per instance."
                ),
            )
        )

    for inventory in inventories:
        if inventory.bazarr_languages is None:
            findings.append(
                PolicyFinding(
                    code="inventory-unavailable",
                    severity="info",
                    message=(
                        f"Bazarr '{inventory.instance_name}' is unreachable — "
                        "target validation skipped"
                    ),
                    fix_guidance="Re-validate once the instance is reachable.",
                    instance_name=inventory.instance_name,
                )
            )
        else:
            for code in (t for t in targets if t not in inventory.bazarr_languages):
                findings.append(
                    PolicyFinding(
                        code="target-not-wanted",
                        severity="warn",
                        message=(
                            f"Target {code!r} is missing from Bazarr "
                            f"'{inventory.instance_name}' language profiles"
                        ),
                        fix_guidance=(
                            "Bazarr never 'wants' languages outside its "
                            "profiles (FR-DR4); add the language to a Bazarr "
                            "language profile or drop the target."
                        ),
                        instance_name=inventory.instance_name,
                    )
                )
        if inventory.lingarr_targets is not None:
            for code in (
                t for t in targets if not _lingarr_knows(t, inventory.lingarr_targets)
            ):
                findings.append(
                    PolicyFinding(
                        code="target-not-in-lingarr",
                        severity="warn",
                        message=(
                            f"Target {code!r} is not among Lingarr's configured "
                            f"target languages for '{inventory.instance_name}'"
                        ),
                        fix_guidance=(
                            "Add the language in Lingarr (Settings → "
                            "Languages) or drop the target (FR-DR6)."
                        ),
                        instance_name=inventory.instance_name,
                    )
                )
        if inventory.lingarr_sources is not None:
            for code in (
                s for s in sources if not _lingarr_knows(s, inventory.lingarr_sources)
            ):
                findings.append(
                    PolicyFinding(
                        code="source-not-in-lingarr",
                        severity="warn",
                        message=(
                            f"Source preference {code!r} is not among Lingarr's "
                            f"configured source languages for "
                            f"'{inventory.instance_name}'"
                        ),
                        fix_guidance=(
                            "Add the language in Lingarr (Settings → "
                            "Languages) or remove it from the preference order."
                        ),
                        instance_name=inventory.instance_name,
                    )
                )
    return findings
