# Troubleshooting

## Lingarr automation conflict (read this first)

**Do not run Lingarr's own automation alongside Perevoditarr.** Lingarr has built-in
automation (`automation_enabled`, `max_translations_per_run`, movie/show age thresholds,
alternating cycles) that translates files **directly and invisibly to Bazarr**. Bazarr
never registers those files and will never upgrade them. Running it alongside
Perevoditarr causes three concrete problems:

1. **Double work and wasted spend** — the same items are translated twice, once by
   Lingarr's automation and once through Perevoditarr's Bazarr-driven path. On paid
   providers this doubles your bill.
2. **Dedup collisions** — Lingarr's `/translate/content` deduplicates on
   `MediaId + MediaType + Title + SourceLanguage + TargetLanguage`. When two
   translations for the same key race, the second gets an **empty array** back as a
   "successful" response.
3. **The empty-array corruption trap (PRD 6.4)** — Bazarr treats that empty array as a
   valid result, maps zero translated lines, and **saves the file anyway**. The result
   is a file in the target language containing *untranslated source text*, recorded in
   Bazarr history as a successful translation. The library is silently corrupt for that
   item, and everything upstream believes the subtitle exists.

**Fix:** disable automation in Lingarr (Settings -> Automation) and let Perevoditarr
drive translation through Bazarr. The configuration doctor detects this and flags it as
**critical** (check **FR-DR2**, "Lingarr automation_enabled is ON"). Perevoditarr's own
scheduling invariant (at most one in-flight translation per instance + series/movie +
source->target language pair) makes the corruption trap unreachable for its own traffic,
but it cannot protect you from Lingarr translating in parallel behind its back. See the
[doctor reference](doctor-reference.md).

## Telemetry shows "polling" instead of live

Perevoditarr has two planes. The **correctness plane** (the intent state machine) runs
only on durable evidence from polling and reconciliation. The **telemetry plane** drives
live UI (progress bars, queue liveness) from Bazarr's Socket.IO stream and Lingarr's
SignalR hubs, and **degrades gracefully to polling** when websockets are unavailable
(commonly blocked by a reverse proxy that does not forward upgrade headers).

- The status bar shows a live-vs-polling indicator, and the doctor surfaces degraded
  streams as an **info** finding (check **FR-DR13**).
- A telemetry mismatch is cosmetic only — it never drives a state transition, so
  correctness is unaffected. Progress may look stale or update on the polling interval.
- To restore live telemetry, allow websocket upgrades through your proxy to Bazarr and
  Lingarr. The polling fallback refresh interval is
  `PEREVODITARR_TELEMETRY_POLL_INTERVAL_SECONDS` (default 30 s); setting it to `0`
  disables the telemetry plane entirely.

## Circuit breaker tripped ("open" or "half-open")

When Lingarr or its provider fails repeatedly (provider down, quota exhausted), the
per-instance-pair circuit breaker trips. Failures are classified, not just counted:

- **open** — the breaker tripped after N consecutive failures; dispatch to that
  instance-pair is held.
- **half-open** — the breaker is probing for recovery; it auto-closes with a
  notification when the probe succeeds.

The doctor surfaces a non-closed breaker as a **warn** finding (check **FR-DR12**), and
the dashboard rails gauges show the breaker state. You are notified on trip and on close.
Investigate the underlying Lingarr/provider outage; the breaker recovers on its own once
the provider is healthy. Note that Perevoditarr performs **no transport-level retries**
(check FR-DR9) — retry semantics live at the intent level only, so it never stacks
retries on top of Bazarr's own 3x toward Lingarr.

## Items in quarantine or needs-attention

Perevoditarr never fails silently into logs. Problem items land in one of two surfaces
in the queue view:

- **Needs attention** — *environmental* failures such as a missing source file or a
  broken path mapping. These are parked without burning retries, because retrying will
  not help until you fix the environment. Resolve the underlying issue, then release the
  item.
- **Quarantine** — *poison* items that failed deterministically N times
  (`PEREVODITARR_DISPATCH_MAX_ATTEMPTS`, default 4, with exponential backoff between
  auto-retries). Each quarantined intent carries full context. From the UI you can
  retry it (re-admit for dispatch), release it, or exclude it.

Transient failures (network blips, timeouts) do not quarantine an item; they become
retry-eligible after re-verification, honoring intent-level backoff between
`PEREVODITARR_DISPATCH_RETRY_BASE_SECONDS` and `PEREVODITARR_DISPATCH_RETRY_CAP_SECONDS`.

## Nothing is being dispatched

If the queue is idle, check, in order:

1. **Preset** — the **Observe** preset dispatches nothing by design. Activate the
   instance (see [onboarding](onboarding.md)).
2. **Pause** — a global or per-instance pause is persisted across restarts.
3. **Rails** — every limiting rail shows a visible explanation (for example "Paused:
   daily cap reached (200/200), resets in 6 h 12 m"). Check volume caps, budget
   ceilings, scheduling windows, and backpressure (a deep Bazarr pending queue holds
   top-up).
4. **Doctor criticals** — unresolved critical findings (unreachable instance, wrong
   `translator_type`, no Lingarr service) mean there is nothing safe to dispatch.

## Registration rejected: version too old

Perevoditarr requires **Bazarr >= v1.5.6** (for the asynchronous jobs queue the dispatch
model assumes) and **Lingarr >= 1.2.4**. Older instances are refused at registration
with a clear error. Upgrade the instance and register again.

## Startup or boot failures

- **Invalid database URL** — only `postgresql+asyncpg://` and `sqlite+aiosqlite://`
  schemes are accepted.
- **Missing secret key in production** — when `PEREVODITARR_ENV=prod`,
  `PEREVODITARR_SECRET_KEY` is required and must be at least 32 characters, or the app
  fails fast at boot.
- **Invalid trusted proxies** — every `PEREVODITARR_TRUSTED_PROXIES` entry must be a
  valid CIDR; forward-auth without a trusted-proxy allowlist is a critical doctor
  finding (FR-DR11).
