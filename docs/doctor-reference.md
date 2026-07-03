# Configuration doctor reference

The configuration doctor detects odd, missing, or mismatched settings across Bazarr,
Lingarr, and Perevoditarr, and reports each finding with a severity, a plain-language
explanation, and fix guidance. It runs on demand (UI button or CLI), on a schedule
(`PEREVODITARR_DOCTOR_INTERVAL_SECONDS`, default daily), and contextually (for example
on instance registration).

## The doctor is read-only in v1

In v1 the doctor **only reads and reports**. It never changes a setting in Bazarr,
Lingarr, or Perevoditarr, and it never dispatches. Remediation is manual: it tells you
what is wrong and how to fix it, and you make the change in the relevant application.
Whether a later version offers explicit opt-in "fix it" writes is an open question and
is not part of v1.

## Severities

Each finding carries one of three severities:

- **critical** — will cause wrong behavior, wasted spend, or data corruption; resolve
  before activating.
- **warn** — likely to cause missing work or degraded results; review.
- **info** — informational context and confirmations (recorded inventory, version and
  capability report, confirmations that a safe default is in place).

The `perevoditarr run-doctor` CLI prints one line per finding as
`[SEVERITY] CHECK_ID: message`, then a summary count of critical/warning/info, and exits
with status `2` when any critical finding is present.

## Check catalogue

Each check maps to a functional requirement key (FR-DR*). A single check can emit
several findings at different severities depending on what it observes.

| Check | Highest severity | What it verifies |
|---|---|---|
| **FR-DR1** — translator wiring | critical (warn for token) | Bazarr is reachable, its `translator_type` is `lingarr`, a Lingarr URL is set, and Lingarr is reachable from Perevoditarr. A missing Lingarr API token is a warning (only a problem if Lingarr requires auth). |
| **FR-DR2** — Lingarr automation | critical | Lingarr's own automation (`automation_enabled`) is off. See below. |
| **FR-DR3** — upgrade translated | warn | Bazarr's "Upgrade Manually Downloaded or Translated Subtitles" is enabled, so translations are not dead-ends. |
| **FR-DR4** — language profiles | warn (info inventory) | Bazarr language profiles exist and carry languages; records the language inventory that profile targets are validated against. |
| **FR-DR5** — Lingarr service | critical | Lingarr has a translation service configured, otherwise every translate call fails. |
| **FR-DR6** — language-code edge cases | warn/info | zh/zt/pb code conversions (Bazarr converts these before calling Lingarr) versus Lingarr's configured code format and languages. |
| **FR-DR7** — subtitle validation limits | warn | Lingarr's subtitle validation limits (for example max file size) are not so tight that realistic subtitles are rejected. |
| **FR-DR8** — concurrency headroom | warn | Bazarr's `concurrent_jobs` leaves headroom over Perevoditarr's effective dispatch window. |
| **FR-DR9** — transport retry ban | critical (info when disabled) | Perevoditarr's own HTTP transport performs no retries (retries stack on top of Bazarr's 3x toward Lingarr; retry logic lives at intent level only). |
| **FR-DR10** — version/capability report | info | Per-instance Bazarr/Lingarr version and detected capability report. |
| **FR-DR11** — operational sanity | warn/critical | Library mirror freshness (never-synced or stale beyond 24 h is a warning) and auth sanity (forward-auth enabled without a trusted-proxy allowlist is critical). |
| **FR-DR12** — circuit breaker state | warn | Surfaces a provider circuit breaker that is open or half-open for an instance-pair. |
| **FR-DR13** — telemetry stream health | info | Surfaces telemetry streams that have fallen back to polling instead of live websockets. |

> Check IDs are the values emitted by the doctor. FR-DR12 (circuit breaker) and FR-DR13
> (telemetry stream health) were added after the original FR-DR1..FR-DR11 numbering, so
> the transport-retry ban keeps its FR-DR9 ID while breaker and telemetry checks use the
> higher numbers.

## FR-DR2: the Lingarr automation conflict (critical)

This is the single most important finding to clear before you activate. Lingarr has its
own automation (`automation_enabled`, `max_translations_per_run`, age thresholds,
alternating cycles) that translates files **directly and invisibly to Bazarr**. Running
it alongside Perevoditarr causes:

- **Double work and wasted spend** — the same items get translated twice.
- **Dedup collisions** — concurrent translations for the same
  `MediaId + MediaType + Title + SourceLanguage + TargetLanguage` trip Lingarr's dedup
  path, which returns an empty array that Bazarr saves as a "successful" translation.
  This is the duplicate-translation corruption trap (PRD 6.4): a file in the target
  language containing untranslated source text, recorded as a success.

When the doctor finds `automation_enabled` is on for a reachable Lingarr, it emits a
**critical** finding: "Lingarr automation_enabled is ON". The fix is to disable
automation in Lingarr (Settings -> Automation) and let Perevoditarr drive translation
through Bazarr. See the [troubleshooting guide](troubleshooting.md) for the full
explainer.
