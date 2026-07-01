# Perevoditarr — Product Requirements Document

| | |
|---|---|
| **Product** | Perevoditarr (from Russian *перево́дчик*, "translator", with the -arr ecosystem suffix) |
| **Document status** | Draft v1.0 |
| **Date** | 2026-07-02 |
| **Scope** | Product requirements. Technical design documents, implementation plans, and API specifications derive from this PRD. |

---

## 1. Executive summary

Perevoditarr is a self-hosted orchestration and observability application that sits between **Bazarr** (subtitle management) and **Lingarr** (subtitle translation). It automates the process of requesting subtitle translations *through Bazarr's API* — so that every translated subtitle remains fully tracked, upgradeable, and native to Bazarr's state — while providing deep, real-time monitoring of both applications, granular automation controls with layered policies and presets, hard safety rails (caps, budgets, circuit breakers), and a modern web UI.

Perevoditarr replaces the community `bazarr_autotranslate` script, which proved the concept but is a stateless polling loop with no persistence, no limits, no UI, and an architecture built against a Bazarr API contract that no longer exists. Perevoditarr is a ground-up rethink: a **declarative reconciliation engine** that treats Bazarr's library as the source of truth, expresses translation goals as durable *intents*, and converges the world toward them safely — designed to work **with** the Bazarr and Lingarr APIs and their internal behaviors, never against them.

Perevoditarr is strictly an orchestrator. It never translates anything itself, never writes subtitle files, and requires **no filesystem access to the media library** — it is a pure API citizen of the ecosystem.

---

## 2. Development governance

> This section intentionally sits at the top of the document. It binds all downstream work.

1. **Rules compliance.** All engineering work derived from this PRD — technical design documents, implementation plans, scaffolding, and code — MUST follow the coding guidelines in **`.augment/rules/*.md`**. As of this writing these comprise the backend guidelines (Litestar / Granian / msgspec / SQLAlchemy async Python stack) and the frontend guidelines (Bun / Svelte 5 / SvelteKit 2 / UnoCSS presetWind4 / shadcn-svelte stack). Where this PRD and the rules files conflict on implementation idiom, the rules files win; where they conflict on product behavior, this PRD wins.
2. **Modular codebase.** The codebase MUST be modular from the first commit: feature-oriented packages with categorized subfolders, clear layering (transport/API ↔ domain/services ↔ infrastructure/persistence), no god-modules, and no cross-feature imports that bypass public module interfaces. Each bounded area of the system described in this PRD (instances, mirror, policy, intents/dispatch, doctor, telemetry, notifications, auth, integrations) maps to its own module on both backend and frontend.
3. **API-first.** Perevoditarr's own web UI consumes the same versioned, documented REST API (`/api/v1`, OpenAPI-generated) that it exposes to users. No private UI-only endpoints.
4. **No reliance on upstream changes.** Design opportunities that would be fixed by upstream PRs to Bazarr or Lingarr are recorded (§6.6) and slots for capability detection are kept, but **no feature may depend on an unreleased or unmerged upstream change**. Bazarr in particular is maintained by a single maintainer with long release cycles; the seam as it exists in the pinned versions is the permanent design target.

---

## 3. Background and problem statement

### 3.1 The ecosystem

- **Bazarr** manages subtitles for Sonarr/Radarr libraries: it knows which languages each episode/movie *should* have (language profiles), which are missing ("wanted"), downloads subtitles from providers, and can *upgrade* subtitles when better versions appear.
- **Lingarr** translates subtitle content using configurable services (LibreTranslate, DeepL, OpenAI, Anthropic, Gemini, DeepSeek, local AI, Google) with its own settings for batching, retries, validation, and prompts.
- Bazarr can be configured to **delegate translation to Lingarr** (`Settings → Subtitles → Translating`). When a translation is requested through Bazarr, Bazarr extracts the subtitle lines, sends them to Lingarr's `/api/translate/content` endpoint, writes the translated file itself, and records the result in its own history — making the translated subtitle a first-class, upgradeable Bazarr object.

### 3.2 The gap

Bazarr has **no automation** for translation: every translation must be requested manually. Lingarr *has* automation, but when Lingarr translates on its own it writes files directly, invisibly to Bazarr — Bazarr never registers them and will never upgrade them. The correct path (automatic, but through Bazarr) has no first-class tool.

### 3.3 Prior art and its limits

`bazarr_autotranslate` (Python script, Aug 2025) fills the gap minimally: it polls Bazarr's wanted lists, matches missing languages against configured source languages, and fires translate requests. Its own README warns that it has **no error limits, no rate limiting, no translation cap** and can cause unexpected charges. It has no persistence (restart = amnesia), no UI, no history, no verification, environment-variable-only configuration, and a thread/timeout architecture built for Bazarr's *old synchronous* translate endpoint. It is a proof of concept, not a product.

### 3.4 The opportunity

A purpose-built application that: automates translation through the correct (Bazarr) path; observes both applications deeply using the full power of both APIs; gives users granular, layered control over automation behavior with safe defaults and presets; enforces hard safety rails; explains every action it takes; and scales to libraries of 100,000+ episodes with 2–3 subtitles each.

---

## 4. Goals and non-goals

### 4.1 Goals

| # | Goal |
|---|---|
| G1 | Fully automate subtitle translation via Bazarr's API so all translations remain Bazarr-tracked and upgradeable. |
| G2 | Deep, real-time monitoring of Bazarr and Lingarr: library state, wanted subtitles, translation execution, job/queue status, statistics, health. |
| G3 | Granular, layered automation controls (global → preset → profile → per-item) with sensible defaults and shippable presets. |
| G4 | Hard safety rails: admission control, volume caps, budget ceilings, scheduling windows, circuit breakers, failure quarantine. Safe-by-default (dry-run first). |
| G5 | Configuration doctor: detect odd, missing, or mismatching settings across Bazarr, Lingarr, and Perevoditarr, with severity and guidance. |
| G6 | Multiple Bazarr (and associated Lingarr) instances — 4K, Anime, etc. — as a first-class concept. |
| G7 | Full explainability: every automated action carries the rule chain that produced it; complete durable audit history. |
| G8 | Modern, fast web UI over a local mirror of library state; real-time updates. |
| G9 | Built-in authentication plus external auth (OIDC — Authentik, Authelia, etc.; forward-auth proxies such as tinyauth; LDAP). |
| G10 | Outbound notifications via Apprise. |
| G11 | Watch-aware prioritization via Tautulli, Plex, and Jellyfin. |
| G12 | Never conflict with Bazarr's or Lingarr's own mechanisms: respect their queues, retries, dedup, settings, and defaults. |

### 4.2 Non-goals

| # | Non-goal |
|---|---|
| N1 | Performing translations itself, in any form. Lingarr translates; Bazarr writes files. |
| N2 | Reading or writing media/subtitle files on disk. No volume mounts to the library are required or supported as a feature. |
| N3 | Replacing the Bazarr or Lingarr UIs for their own domains (provider config, translation service config, etc.). |
| N4 | Writing configuration into Bazarr or Lingarr. The doctor is **read-only in v1**; opt-in remediation is a recorded future consideration, not a commitment. |
| N5 | Managing subtitle *downloads* (Bazarr's provider search domain). |
| N6 | Supporting Bazarr versions older than the pinned minimum (§6.1). No legacy synchronous-endpoint mode. |

---

## 5. Users and use cases

**Primary persona:** the self-hosting media-server operator (Sonarr/Radarr/Bazarr/Plex-or-Jellyfin stack, Docker-based, often multiple instances), technically capable, cost-conscious about paid translation APIs, and burned before by runaway automation.

Representative use cases:

1. *"My library has 40,000 episodes and my language profile wants Danish. English subs exist for most. Translate the backlog to Danish — but never more than 200/day, only between 02:00–08:00, newest and actually-watched shows first, and show me what you'd do before you do anything."*
2. *"I run a normal stack and a 4K stack, plus an anime instance where the source language should prefer Japanese-timed English subs. Different rules per instance and per library."*
3. *"Tell me if my setup is subtly broken — Bazarr not actually pointed at Lingarr, Lingarr's own automation fighting us, upgrade setting off, target language missing from Bazarr profiles."*
4. *"Ping my Discord when the daily cap is hit, when the circuit breaker trips, and with a nightly digest."*
5. *"Someone added a new show yesterday; its episodes should be translated soon after the grace period, without me touching anything."*

---

## 6. Integration reality — code-derived constraints (normative)

This section records how Bazarr and Lingarr *actually behave* at the seam, established by direct code research of Bazarr master (validated against the v1.5.6 release line) and Lingarr main (May 2026). These findings are **normative constraints** on all downstream design. Section references: Bazarr `bazarr/api/subtitles/subtitles.py`, `bazarr/app/jobs_queue.py`, `bazarr/subtitles/tools/translate/*`; Lingarr `Lingarr.Server/Controllers/*`, `Lingarr.Server/Services/TranslationRequestService.cs`, `Lingarr.Core/Configuration/SettingKeys.cs`, `Lingarr.Server/Jobs/AutomatedTranslationJob.cs`.

### 6.1 Version pinning

- **Bazarr: minimum supported version v1.5.6** (the current release as of this document). Perevoditarr performs a version check on instance registration and refuses older instances with a clear error. Rationale: v1.5.x introduced the asynchronous jobs queue that the entire dispatch model assumes; supporting the old synchronous PATCH would require holding HTTP connections open for minutes and a parallel legacy architecture.
- **Lingarr: minimum version = the release line validated during research** (main branch as of 2026-05); the exact version number is pinned at implementation start and enforced the same way.

### 6.2 Bazarr's translate path is asynchronous, anonymous, and ephemeral

- `PATCH /api/subtitles?action=translate&…` **enqueues** an internal job and returns `204` immediately.
- The response **does not include the job ID**. Correlating a specific request to a specific Bazarr job is only possible fuzzily (job name contains language pair and translator type; progress message contains the source file path).
- Bazarr's job queues are **in-memory**: pending/running are unbounded deques, **failed and completed are capped at 10 entries each**, and everything is lost on restart. `GET/POST/PATCH/DELETE /api/system/jobs` provides live listing (by status), force-start, reorder, and delete.
- The queue is **shared** across all Bazarr work (library syncs, searches, translations) and consumed with concurrency `settings.general.concurrent_jobs`.

**Consequences:** Bazarr's job queue must never be used as a backlog store or as a correctness signal. It is a *transient dispatch buffer* and a *backpressure signal* only.

### 6.3 The Bazarr→Lingarr contract

- Bazarr POSTs subtitle **lines** (position + text) to Lingarr `POST /api/translate/content` with media context: `arrMediaId`, `title`, `sourceLanguage`, `targetLanguage`, `mediaType` (`Episode`/`Movie`). Auth via `X-Api-Key` when configured. Timeout 1800 s.
- Bazarr's Lingarr client **already retries 3× with exponential backoff + jitter** on 429/5xx/timeouts/connection errors. Lingarr additionally has its own internal retry settings (`max_retries`, `retry_delay`, `retry_delay_multiplier`) toward the translation service.
- Bazarr converts language codes before calling Lingarr: `zh→zh-CN`, `zt→zh-TW`, `pb→pt-BR`.
- On success Bazarr writes the translated file, optionally appends translator info, indexes it, and logs history **action = 6** (translation) for the episode/movie.

**Consequences:** Perevoditarr MUST NOT add its own per-request retry layer (retry stacking would multiply provider calls up to 9× per failure); its retry semantics operate at the *intent* level after verification, never at the HTTP transport level. Language-code edge cases must be handled/validated at policy level.

### 6.4 The duplicate-translation corruption trap (critical)

Lingarr's `/translate/content` deduplicates: if an active (Pending/InProgress) `TranslationRequest` already exists with the same `MediaId + MediaType + Title + SourceLanguage + TargetLanguage`, it **returns an empty array** as a successful response. Bazarr treats an empty array as valid, maps zero translated lines, and **saves the file anyway** — producing a file in the target language containing *untranslated source text*, recorded in Bazarr history as a successful translation. The library is then silently corrupt for that item: everything upstream believes the subtitle exists.

**Consequences:** Deduplication in Perevoditarr is a data-integrity requirement, not an optimization. Perevoditarr MUST make this path unreachable for its own traffic (see §6.5 and FR-D4) and SHOULD guard against racing external actors (pre-dispatch checks against Bazarr wanted state and Lingarr active requests).

### 6.5 Episode identity is coarse inside Lingarr

For episodes, Bazarr sends `arrMediaId = sonarr_series_id` (the **series** ID) with `mediaType=Episode`, and a `title` equal to the **show title** (no season/episode). Lingarr resolves that value as if it were a Sonarr *episode* ID (typically failing to a sentinel value). Net effect: a Bazarr-delegated episode translation appears in Lingarr identified only at **show + language-pair** granularity; two concurrent episodes of the same show translating to the same target are **indistinguishable** — and the second one trips the §6.4 dedup path. Movies map correctly (Radarr movie ID + movie title) and are exactly identifiable.

**Consequence — the core scheduling invariant:** Perevoditarr MUST enforce **at most one in-flight translation per (Bazarr instance, series, source→target language pair)** for episodes, and per (instance, movie, source→target pair) for movies. This invariant simultaneously (a) makes Lingarr's coarse records deterministically attributable to exactly one Perevoditarr intent, (b) makes the corruption trap unreachable by construction for Perevoditarr-originated traffic, and (c) costs little throughput at library scale, since the dispatch window fills with work from different series.

### 6.6 Upstream opportunities (tracked, never relied upon)

Two small upstream improvements would sharpen telemetry: Bazarr returning the job ID from the translate PATCH, and Bazarr sending `sonarr_episode_id` (plus an episode-aware title) to Lingarr. Both are recorded as potential future PRs. Per §2.4 and explicit product direction: **no Perevoditarr feature depends on them.** Perevoditarr ships per-instance **capability detection** so that, if a future Bazarr/Lingarr version improves the seam, telemetry correlation upgrades automatically and the §6.5 invariant may be relaxed for that version pair — but the shipped design is complete and correct without any upstream change.

### 6.7 Lingarr's competing automation and authoritative settings

- Lingarr has its own automation (`automation_enabled`, `max_translations_per_run`, movie/show age thresholds, alternating cycles) that translates files **directly and invisibly to Bazarr**. Running it alongside Perevoditarr causes double work, wasted spend, and dedup collisions. The doctor MUST detect and flag it (FR-DR checks).
- Lingarr owns provider-level behavior: service selection, batching (`use_batch_translation`, `max_batch_size`), retries, request timeout, subtitle validation limits, prompts/templates, `source_languages`/`target_languages`, and `language_code_format`. Perevoditarr treats these as authoritative, reads them via Lingarr's settings API for the doctor and for planning, and never duplicates or overrides their function.
- Lingarr provides rich observability Perevoditarr consumes: `TranslationRequest` records (durable; per-request detail, paginated history, active list; cancel/retry/resume/remove actions), a statistics endpoint, and three SignalR hubs (job progress, translation requests, setting updates).

### 6.8 Observability planes and their trust levels

| Plane | Source | Durability | Perevoditarr's use |
|---|---|---|---|
| Library truth | Bazarr metadata (`/api/episodes`, `/api/movies`), wanted lists | Durable (Bazarr DB) | **Authoritative** convergence evidence: the subtitle exists / is no longer wanted |
| Outcome record | Bazarr history (action 6 = translation) | Durable (Bazarr DB) | Corroboration: converged *via translation* within the intent's lease window (vs. superseded by an indexer download) |
| Execution detail | Lingarr `TranslationRequest` records + active list | Durable (Lingarr DB) | Running/failed/cancelled status and failure reasons, at §6.5 granularity |
| Live telemetry | Bazarr Socket.IO event stream; Lingarr SignalR hubs | Ephemeral | UI progress and liveness **only** — never state transitions (§7.3) |

---

## 7. System architecture principles (product-level)

Full technical design follows in separate documents; this section fixes the load-bearing decisions.

### 7.1 Declarative reconciliation, not imperative job tracking

Perevoditarr is a **reconciliation controller**. It maintains a durable **intent ledger**: one intent per desired translation, keyed by natural identity `(bazarr_instance, media_id, target_language, forced, hi)`, with lifecycle:

```
discovered → eligible → dispatched → converged
                                   → superseded
                                   → failed → (retry-eligible | quarantined)
```

- **Discovery** derives intents from Bazarr's wanted state joined with policy (eligible source subtitle exists, target is in policy, grace period passed, not excluded).
- **Dispatch** fires the Bazarr translate PATCH (fast 204) and stamps the intent with a **lease** — a deadline by which convergence evidence is expected.
- **Convergence** is decided **only from durable evidence** (§6.8): the subtitle exists in Bazarr metadata, corroborated by a history action-6 entry within the lease window. A subtitle that appeared by other means (indexer download, manual action) marks the intent `superseded`.
- **Failure** is decided from Lingarr request status (Failed/Cancelled ⇒ immediate, with reason) or lease expiry without evidence ⇒ verification then classification.
- The reconciler re-observes the world periodically and on telemetry events. **Crash safety is inherent:** after a restart, re-observation retroactively converges, supersedes, or re-eligibilizes intents; there is no volatile state to lose.

### 7.2 Bounded dispatch window (admission control)

Perevoditarr holds the backlog; Bazarr's queue is kept shallow. At most **K** intents are dispatched concurrently per Bazarr instance (default 2, configurable), always leaving headroom relative to that instance's `concurrent_jobs`, and the dispatcher consults Bazarr's jobs API as a backpressure signal (deep pending queue ⇒ hold off). The §6.5 invariant (one in-flight per series+language-pair / movie+language-pair) is enforced inside the window. Priority ordering decides what fills freed slots (§9.5).

### 7.3 Two-plane separation: correctness vs. telemetry

The **correctness plane** (intent state machine) runs exclusively on durable evidence gathered by polling + reconciliation. The **telemetry plane** consumes Bazarr's Socket.IO stream and Lingarr's SignalR hubs for live UI (progress bars, queue liveness, "translating line 340/812") with **graceful degradation to polling** when websockets are unavailable (blocked by proxies, etc.). Telemetry may use fuzzy correlation (job names, file paths, §6.5-granularity matching) because a telemetry mismatch costs a cosmetic glitch, never a wrong state transition. No telemetry event may drive the intent state machine.

### 7.4 Failure taxonomy and safety posture

Failures are classified, not counted: **transient** (network blips, timeouts → intent becomes retry-eligible after re-verification, honoring backoff at intent level), **environmental** (source file missing, path mapping broken → parked, surfaced in "needs attention," no retry burn), **provider/systemic** (Lingarr down, provider quota exhausted → circuit breaker per instance-pair: trip after N consecutive failures, half-open probe every M minutes, auto-close with notification), and **poison** (deterministic per-item failure ×N → quarantined with full context). Nothing fails silently into logs.

### 7.5 Pure API citizenship

Perevoditarr requires network access to Bazarr/Lingarr (and optional Tautulli/Plex/Jellyfin) APIs only. No media volume mounts. Its single write surface toward the ecosystem is Bazarr's translate PATCH (plus optional, user-initiated Lingarr request actions such as cancel/retry surfaced in the UI, which map 1:1 to Lingarr's own endpoints).

---

## 8. Configuration model: layered policies and presets

### 8.1 The cascade

Effective automation behavior for any media item resolves through a strict cascade, most specific wins:

```
Global defaults → Active preset → Translation profile (assigned to instance/library/series/movie) → Per-item override
```

Every effective setting shown in the UI displays its **provenance** ("inherited from preset *Balanced* — override?"). Overrides are explicit, visible, and revocable at each layer.

### 8.2 Translation profiles

A profile bundles the *what* and *how* of translation for the media it is assigned to:

- Target languages (validated against the Bazarr instance's language profiles — targets Bazarr doesn't "want" never appear as wanted and are flagged by the doctor).
- Source language preference **ordering** (e.g. prefer `en`, fall back to `de`), with HI/forced source handling rules.
- Grace period after airing/import (real subtitles often appear within days; translating immediately wastes money). Separate movie/show values, consistent in spirit with Lingarr's own age-threshold concept.
- Skip conditions: target exists as embedded track (optional), item unmonitored, item/series/tag excluded.
- HI/forced target policy.

### 8.3 Presets

Shippable, forkable bundles of defaults constituting the onboarding story:

| Preset | Posture |
|---|---|
| **Observe** (default on install) | Dry-run only. Discovers, plans, reports. Dispatches nothing. |
| **Conservative** | K=1, low daily cap, long grace periods, tight breaker. |
| **Balanced** | Moderate caps and window, budget ceiling on, sane defaults for paid providers. |
| **Aggressive** | Higher K and caps, short grace, for free/local providers. |

Presets are duplicatable, editable, and **exportable/importable as JSON** for community sharing.

### 8.4 Safety rails (independent, composable mechanisms)

| Mechanism | Protects | Notes |
|---|---|---|
| Dispatch window (K per instance) | Bazarr's shared queue; Lingarr load | §7.2; headroom vs. `concurrent_jobs`; backpressure-aware |
| Scheduling invariant | Data integrity | §6.5; non-configurable |
| Volume caps | Wallet, runaway loops | Per hour/day/week; per instance and global |
| Budget ceilings | Wallet | Estimated characters/lines per period vs. limit; estimates from rolling actuals (Lingarr statistics + own history) and runtime heuristics; actuals reconciled after completion |
| Scheduling windows | Server load, shared LLM boxes | Cron-like active windows per instance/profile |
| Circuit breakers | Provider/Lingarr outages | §7.4; per instance-pair; half-open recovery; notify on trip/close |
| Global & per-instance pause | Everything | One click; state persists across restarts |
| Dry-run at any layer | Confidence | Any profile or instance can be dry-run while others are active |

Every rail that is currently limiting has a visible UI explanation: *"Paused: daily cap reached (200/200), resets in 6 h 12 m."*

---

## 9. Functional requirements

Requirement keys: FR-XN. Priorities: **P0** = must ship in v1.0, **P1** = should ship in v1.x, **P2** = future.

### 9.1 Instances (FR-I)

| ID | P | Requirement |
|---|---|---|
| FR-I1 | P0 | Register multiple Bazarr instances (name, URL, API key). Connection test, **version check ≥ v1.5.6** with clear rejection otherwise, and capability probe on registration and periodically. |
| FR-I2 | P0 | Auto-discover each Bazarr instance's configured Lingarr (URL/token from Bazarr's settings API) with one-click confirmation; manual Lingarr registration also supported. Multiple Bazarr instances may share one Lingarr. |
| FR-I3 | P0 | Per-instance health: reachability, latency, version, queue depth, breaker state; surfaced on dashboard and in doctor. |
| FR-I4 | P0 | All domain data is instance-scoped (`instance_id` on every relevant entity). |
| FR-I5 | P1 | Per-instance enable/disable and per-instance dispatch settings (K, caps) overriding globals. |

### 9.2 Library mirror & sync (FR-M)

| ID | P | Requirement |
|---|---|---|
| FR-M1 | P0 | Mirror series, episodes, movies, existing subtitles, and wanted (missing) subtitles per instance into Perevoditarr's database. The UI reads the mirror, never Bazarr directly, for browsing at scale. |
| FR-M2 | P0 | Incremental sync on schedule (configurable interval) plus event-triggered refresh from the telemetry plane; full resync on demand. |
| FR-M3 | P0 | Mirror scale target: 100,000+ episodes and 300,000+ subtitle rows per instance with responsive pagination/filter/search. |
| FR-M4 | P1 | Track mirror freshness per instance; stale mirrors flagged in UI and doctor. |

### 9.3 Discovery & policy engine (FR-P)

| ID | P | Requirement |
|---|---|---|
| FR-P1 | P0 | Derive intents from wanted subtitles × policy cascade (§8): target in profile, eligible source exists per preference order, grace period passed, no skip condition. |
| FR-P2 | P0 | Full cascade (global → preset → profile → item) with provenance display and per-layer override. |
| FR-P3 | P0 | Exclusions: per series/movie ("never translate"), per language pair, and tag-based. |
| FR-P4 | P0 | Language-code correctness: operate in Bazarr `code2` space; respect the §6.3 conversion cases; validate profile targets against Bazarr language profiles and Lingarr's configured source/target languages (doctor-linked). |
| FR-P5 | P1 | Per-library (root folder / Sonarr-Radarr tag) profile assignment in addition to per-series/movie. |

### 9.4 Intent ledger & reconciliation (FR-R)

| ID | P | Requirement |
|---|---|---|
| FR-R1 | P0 | Durable intent ledger with the §7.1 state machine; unique on natural key; complete transition history per intent (who/what/when/why). |
| FR-R2 | P0 | Evidence-based convergence exactly per §6.8/§7.1: metadata = authoritative, history action-6 within lease = "converged via translation", other appearance = `superseded`. |
| FR-R3 | P0 | Lease management: configurable default informed by observed durations; expiry ⇒ verify ⇒ classify (§7.4). |
| FR-R4 | P0 | Crash-safe recovery by re-observation on startup; no reliance on any volatile state, ours or Bazarr's. |
| FR-R5 | P0 | Intent-level retry with backoff and max attempts for transient class only; environmental/poison park into "needs attention"/quarantine. |
| FR-R6 | P1 | Manual intent actions: force re-verify, retry now, cancel, exclude-from-here-on. |

### 9.5 Dispatch & prioritization (FR-Q)

| ID | P | Requirement |
|---|---|---|
| FR-Q1 | P0 | Bounded dispatch window per §7.2, honoring the §6.5 invariant unconditionally. |
| FR-Q2 | P0 | Pre-dispatch guard: re-verify still-wanted in Bazarr **and** no matching active request in Lingarr (`/api/translationrequest/active`) immediately before PATCH. |
| FR-Q3 | P0 | All §8.4 safety rails enforced at dispatch time; every non-dispatch decision is explainable. |
| FR-Q4 | P0 | Priority scoring: recency of addition/airing, monitored status, continuing vs. ended, movies/episodes weighting, manual bump-to-front; configurable weights per profile. |
| FR-Q5 | P1 | Watch-aware priority inputs (§9.9) folded into scoring when integrations are configured. |
| FR-Q6 | P1 | Backpressure: consult Bazarr jobs API depth before top-up; configurable threshold. |

### 9.6 Verification, history & explainability (FR-V)

| ID | P | Requirement |
|---|---|---|
| FR-V1 | P0 | Every intent carries its **decision trace**: the rule chain that created, prioritized, dispatched, or blocked it (e.g. "profile *Anime* → missing `da` → source `en` chosen over `ja` by preference → grace passed → priority 3 → dispatched 14:02"). |
| FR-V2 | P0 | Durable, filterable, exportable history of all attempts and outcomes — Perevoditarr is the system of record (Bazarr's completed/failed job lists hold only 10 entries). |
| FR-V3 | P0 | Distinguish `converged` vs. `superseded` in stats and budget accounting. |
| FR-V4 | P1 | Per-item timeline view stitching intent events, Lingarr request states, and Bazarr history entries. |

### 9.7 Configuration doctor (FR-DR)

Read-only in v1 (N4). Each check yields severity (info/warn/critical), explanation, and fix guidance. Runs on demand, on schedule, and contextually (e.g. on instance registration). Minimum check set:

| ID | Check |
|---|---|
| FR-DR1 | Bazarr `translator_type` is `lingarr`; Lingarr URL/token set; Lingarr reachable from Bazarr's perspective (config present) and from Perevoditarr. |
| FR-DR2 | **Lingarr `automation_enabled` is off** (critical: competing automation, invisible-to-Bazarr writes, dedup collisions). |
| FR-DR3 | Bazarr "Upgrade Manually Downloaded or Translated Subtitles" enabled (else translations are dead-ends). |
| FR-DR4 | Profile target languages exist in the Bazarr instance's language profiles (else never "wanted"). |
| FR-DR5 | Lingarr translation service configured (service type + credentials); models endpoint reachable for AI providers. |
| FR-DR6 | Language-code edge cases (`zh/zt/pb` conversions; Lingarr `language_code_format`) consistent with configured pairs. |
| FR-DR7 | Lingarr subtitle-validation limits vs. planned traffic (e.g. max file size) — warn on likely rejections. |
| FR-DR8 | Bazarr `concurrent_jobs` vs. Perevoditarr's K: warn when K would monopolize the instance queue. |
| FR-DR9 | Retry-stacking awareness: verify Perevoditarr's transport layer performs no per-request retries (self-check / invariant assertion). |
| FR-DR10 | Version/capability report per instance (Bazarr, Lingarr; detected capabilities per §6.6). |
| FR-DR11 | Mirror freshness, auth config sanity, notification config test. |

### 9.8 Web UI (FR-U)

| ID | P | Requirement |
|---|---|---|
| FR-U1 | P0 | **Dashboard**: per-instance health, coverage per target language, backlog size, in-flight, converged/superseded/failed counts, active rails ("why are we idle"), breaker states. |
| FR-U2 | P0 | **Queue view**: backlog with priorities, in-flight with live progress (telemetry plane), needs-attention and quarantine surfaces; pause/resume, bump, cancel. |
| FR-U3 | P0 | **Plan preview (dry-run view)**: "what would happen next and why," with estimated volume/budget impact — the primary Observe-mode surface. |
| FR-U4 | P0 | **Library browser**: mirror-backed series/episodes/movies with subtitle/coverage state, per-item actions (translate now, exclude, assign profile). |
| FR-U5 | P0 | **History/audit** with decision traces (FR-V1/V2) and per-item timeline (P1: FR-V4). |
| FR-U6 | P0 | **Settings**: instances, profiles, presets (fork/import/export), rails, doctor panel, notifications, auth, integrations. |
| FR-U7 | P0 | Real-time UI updates via SSE from Perevoditarr's own API; no polling loops in the browser for live surfaces. |
| FR-U8 | P1 | Statistics: throughput, durations, failure rates by class, per-provider volume/cost estimates vs. actuals (Lingarr statistics reconciliation). |

### 9.9 Integrations (FR-X)

| ID | P | Requirement |
|---|---|---|
| FR-X1 | P0 | **Apprise** notifications (library-native): breaker trips/recovery, caps reached, quarantine additions, doctor criticals, daily digest; per-event routing config and test button. |
| FR-X2 | P1 | **Tautulli, Plex, Jellyfin** watch-history integrations feeding priority scoring (FR-Q5): recently/frequently watched series and watchlisted items score higher. All three supported; each optional and independent. |
| FR-X3 | P1 | Lingarr request pass-through actions in UI (cancel/retry/resume) mapping 1:1 to Lingarr's endpoints, clearly labeled as acting on Lingarr. |
| FR-X4 | P2 | Webhook ingestion (Bazarr/Sonarr notifications) as additional discovery triggers, complementing polling + telemetry. |

### 9.10 Authentication & security (FR-A)

| ID | P | Requirement |
|---|---|---|
| FR-A1 | P0 | Built-in auth: username/password (Argon2id), sessions, per-user API keys for the REST API. |
| FR-A2 | P0 | **OIDC** (authorization code + PKCE) compatible with Authentik, Authelia, and generic providers. |
| FR-A3 | P0 | **Forward-auth / trusted-header** mode (Remote-User style) for proxy authenticators such as tinyauth and Authelia's proxy mode, with explicit trusted-proxy configuration. |
| FR-A4 | P1 | LDAP bind authentication. |
| FR-A5 | P0 | Secrets (Bazarr/Lingarr/integration API keys) encrypted at rest; never returned in plaintext by the API after write; masked in UI and logs. |
| FR-A6 | P1 | Roles: admin (full) vs. viewer (read-only observer). |

### 9.11 Perevoditarr API (FR-API)

| ID | P | Requirement |
|---|---|---|
| FR-API1 | P0 | Versioned REST API under `/api/v1`, OpenAPI 3.1 schema auto-generated, interactive docs served. |
| FR-API2 | P0 | The bundled web UI consumes exclusively this API (§2.3). |
| FR-API3 | P0 | API-key auth for programmatic access; same authorization model as the UI. |

---

## 10. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Tech stack** per `.augment/rules/*.md`: backend Python 3.14 / Litestar 2.x / Granian (litestar-granian) / msgspec / SQLAlchemy 2.0 async / Advanced Alchemy / Alembic / structlog / httpx, tooling uv + ruff + basedpyright; frontend Bun / Svelte 5 (runes) / SvelteKit 2 / UnoCSS presetWind4 / shadcn-svelte. |
| NFR-2 | **Database: PostgreSQL is the default and recommended engine** (asyncpg), sized for 100k+ episodes × 2–3 subtitles with proper indexing and pagination. **SQLite (aiosqlite) is supported** as a lightweight option for small libraries. All persistence is dialect-portable via SQLAlchemy/Advanced Alchemy; features must not fork on dialect. (Note: persistence lives in the Python backend; Bun's SQLite driver is not applicable.) |
| NFR-3 | **Deployment**: Docker-first, single container by default (SvelteKit built as a static SPA served by the backend; API and UI same-origin). Compose examples provided. Configuration via environment variables + database-backed settings; no config-file editing required. |
| NFR-4 | **Performance**: library browser interactions < 200 ms server time at NFR-2 scale; reconciliation cycles must not degrade UI responsiveness (background scheduling, indexed queries). |
| NFR-5 | **Resilience**: crash-safe per §7.1/FR-R4; idempotent sync; safe concurrent operation of scheduler, reconciler, dispatcher, and telemetry consumers. |
| NFR-6 | **Observability**: structured JSON logging (structlog) with per-intent correlation IDs; health endpoint; Prometheus-style metrics endpoint (P1). |
| NFR-7 | **Real-time**: telemetry consumers speak Socket.IO (Bazarr) and SignalR (Lingarr) as clients with automatic **graceful degradation to polling**; UI real-time via SSE. |
| NFR-8 | **Security**: no default credentials; first-run setup flow; CSRF protection; secrets handling per FR-A5; outbound requests restricted to configured instance URLs. |
| NFR-9 | **Privacy**: no telemetry/phone-home of any kind. |
| NFR-10 | **Modularity** per §2.2, enforced in review; module boundaries documented in the technical design. |
| NFR-11 | **Quality gates**: backend `ruff` + `basedpyright` (recommended mode) + pytest; frontend `svelte-check` + eslint + `bun test`; CI green required. |

---

## 11. Data model (high-level)

Entity families (technical design will refine):

- **instances**: `bazarr_instance`, `lingarr_instance` (linkage N Bazarr → 1 Lingarr allowed), capabilities, health snapshots.
- **mirror**: `series`, `episode`, `movie`, `subtitle` (existing), `wanted_subtitle` — instance-scoped, indexed for browse/filter at NFR-2 scale.
- **policy**: `preset`, `translation_profile`, `profile_assignment` (instance/library/series/movie), `exclusion`, `override`.
- **automation**: `intent` (natural-key-unique, state, lease, priority, decision trace ref), `intent_event` (append-only audit), `dispatch_slot` accounting, `rail_state` (caps counters, breaker states, pause flags — persisted), `quarantine_item`.
- **integrations**: `notification_route` (Apprise), `watch_source` (Tautulli/Plex/Jellyfin) + watch-score cache.
- **auth**: `user`, `session`, `api_key`, `auth_provider_config`.
- **ops**: `doctor_run`/`doctor_finding`, `sync_run`, `settings` (encrypted where sensitive).

---

## 12. Milestones

| Milestone | Contents | Exit criterion |
|---|---|---|
| **M0 — Observer** | Instance registration (version/capability checks), Lingarr auto-discovery, library mirror + sync, dashboard + library browser (read-only), doctor v1, auth (built-in + OIDC + forward-auth), API v1 skeleton | A user can register instances, browse a 100k-episode mirror smoothly, and get a truthful doctor report — with zero write actions available |
| **M1 — Planner (dry-run)** | Policy cascade, profiles, presets, intent ledger + reconciliation in Observe mode, plan preview with volume/budget estimates, decision traces, history | The plan preview is accurate and explainable against a real library; still zero dispatches |
| **M2 — Orchestrator** | Dispatcher with window + invariant + pre-dispatch guards, all safety rails, verification/convergence, failure taxonomy + quarantine, Apprise notifications, queue UI, live telemetry with polling fallback | End-to-end automated translation on a real stack with rails demonstrably enforcing; corruption trap demonstrably unreachable |
| **M3 — Insight & polish** | Statistics + budget reconciliation vs. Lingarr actuals, per-item timelines, preset import/export, Lingarr pass-through actions, metrics endpoint | v1.0 release quality |
| **M4 — Watch-aware & extended auth** | Tautulli/Plex/Jellyfin priority inputs, LDAP, roles, webhook ingestion | v1.x |

---

## 13. Success metrics

1. **Zero** duplicate-induced corrupt subtitle files attributable to Perevoditarr (verified by the §6.4-trap being unreachable in integration tests and absent in field reports).
2. Time-to-first-value: fresh install → truthful doctor report and accurate dry-run plan in **< 10 minutes**.
3. Backlog convergence: measurable, monotonic coverage growth per target language under configured caps; per-day throughput matches configured rails exactly.
4. Every automated action in history carries a complete decision trace (100% explainability).
5. Restart during heavy in-flight load loses no intents and creates no duplicates (crash-safety test suite).
6. UI responsiveness at NFR-2 scale within NFR-4 budgets.

---

## 14. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Bazarr/Lingarr internal behavior changes in future releases (unversioned internals like job-name formats, dedup semantics) | Telemetry degradation or new seams | Pin minimum versions; capability detection per instance; correctness plane depends only on stable, durable surfaces (metadata, history, Lingarr request records); integration test suite against pinned versions |
| Slow upstream release cadence (single maintainer) | Seam improvements never land | Already absorbed: design is complete without upstream changes (§2.4, §6.6) |
| SignalR/Socket.IO client fragility from Python | Telemetry gaps | Two-plane separation makes telemetry loss cosmetic; automatic polling fallback (NFR-7) |
| Budget estimates inaccurate (no file access) | Ceiling over/under-shoot | Estimates from rolling actuals + runtime heuristics, reconciled against Lingarr statistics; ceilings applied conservatively (estimate high) |
| Users run Lingarr automation concurrently | Double spend, dedup collisions | FR-DR2 critical finding, prominent onboarding warning, docs |
| Large-library sync load on Bazarr | Bazarr slowdown | Incremental sync, ETag/paging strategies where available, configurable intervals, backpressure awareness |
| Scope creep (this PRD is ambitious) | Delay | Strict milestone gating; M0–M2 define the product core; everything else follows |

---

## 15. Open questions (non-blocking)

1. **Doctor remediation**: v1 is read-only (decided). Whether a later version offers explicit opt-in "fix it" writes (e.g. disabling Lingarr automation via its settings API) remains open.
2. **Exact Lingarr minimum version string** to pin at implementation start (§6.1).
3. **Roles granularity** beyond admin/viewer (per-instance permissions?) — deferred to M4 scoping.
4. **SQLite operational guidance**: recommended library-size ceiling for the SQLite option, to be established empirically during M0 performance testing.

---

## Appendix A — External API surfaces relied upon

**Bazarr (≥ v1.5.6):** `GET /api/episodes/wanted`, `GET /api/movies/wanted`, `GET /api/episodes`, `GET /api/movies`, `PATCH /api/subtitles` (`action=translate`), `GET/POST/DELETE /api/system/jobs`, `GET /api/system/settings`, `GET /api/system/languages/profiles`, history endpoints (episodes/movies; translation = action 6), `GET /api/system/status`, Socket.IO event stream. Auth: `X-API-KEY`.

**Lingarr (pinned line):** `GET /api/setting/{key}`, `POST /api/setting/multiple/get`, `GET /api/translationrequest/active`, `GET /api/translationrequest/requests`, `GET /api/translationrequest/{id}`, `POST /api/translationrequest/{cancel|retry|resume|remove}`, `GET /api/schedule/jobs`, statistics endpoint, SignalR hubs (`JobProgressHub`, `TranslationRequestsHub`, `SettingUpdatesHub`). Auth: `X-Api-Key`. *(Perevoditarr never calls `POST /api/translate/content` — that is Bazarr's write path.)*

**Optional integrations:** Apprise (library), Tautulli API, Plex API, Jellyfin API.

## Appendix B — Glossary

| Term | Meaning |
|---|---|
| **Intent** | A durable record of one desired translation: (instance, media, target language, forced, hi). |
| **Lease** | The deadline by which a dispatched intent expects convergence evidence. |
| **Converged** | The target subtitle exists in Bazarr, corroborated by a translation history entry within the lease. |
| **Superseded** | The target subtitle appeared by other means (indexer, manual); the intent's goal is met without our translation. |
| **Dispatch window (K)** | Maximum concurrently dispatched intents per Bazarr instance. |
| **Scheduling invariant** | At most one in-flight translation per (instance, series, source→target pair) for episodes; per (instance, movie, pair) for movies. Non-configurable. |
| **Correctness plane / telemetry plane** | Durable-evidence reconciliation vs. best-effort live progress; strictly separated. |
| **Rails** | The composable safety mechanisms of §8.4. |
| **Doctor** | The read-only cross-application configuration checker. |
