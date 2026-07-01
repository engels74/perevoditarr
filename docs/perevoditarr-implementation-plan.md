# Perevoditarr — Implementation Plan

| | |
|---|---|
| **Derived from** | `perevoditarr-prd.md` (Draft v1.0, 2026-07-02) |
| **Governed by** | `.augment/rules/backend-dev-pro.md`, `.augment/rules/frontend-dev-pro.md` (binding for all code; PRD §2) |
| **Structure** | Phases map 1:1 to PRD milestones (Phase 0 = pre-M0 foundations; Phases 1–5 = M0–M4). Tasks carry IDs (`P<phase>-T<n>`) for cross-referencing in issues/PRs. |
| **Rule of thumb** | A task is done only when its subtasks are checked **and** the Phase quality gates pass. |

---

## 0. Standing conventions (apply to every task, every PR)

These are distilled from the rules files and PRD §2/§6. Violations are review blockers.

**Backend (Python 3.14 / Litestar 2.x)**

- [ ] `uv` only (`uv add`, `uv sync`, `uv run`) — never pip/poetry. Commit `uv.lock`.
- [ ] `ruff format` + `ruff check --fix` (2026 style, `target-version = "py314"`, `ASYNC` rules on) and `basedpyright` in `recommended` mode pass on every commit; suppressions only as `# pyright: ignore[ruleName]`, never bare `# type: ignore`.
- [ ] msgspec `Struct`s for all schemas — never Pydantic. Request bodies: `kw_only=True, forbid_unknown_fields=True`; constraints via `Annotated[..., msgspec.Meta(...)]`; tagged unions always tagged; `UNSET` for PATCH semantics.
- [ ] SQLAlchemy 2.0 style exclusively (`select()` + `session.scalars()`); `expire_on_commit=False`; eager loading (`selectinload` for collections, `joinedload` for scalars); `lazy="raise"` as the default relationship guard; **no `from __future__ import annotations` in any ORM model module**.
- [ ] App runs via `litestar run` with `GranianPlugin` — never uvicorn/gunicorn. No blocking I/O in `async def` (ruff `ASYNC` enforces).
- [ ] One long-lived `httpx.AsyncClient` per external system, created in lifespan, stored on `app.state`, closed on shutdown — never per-request clients; never `requests`.
- [ ] **No transport-level retries anywhere in Perevoditarr's HTTP clients** (PRD §6.3 / FR-DR9): retry semantics live at intent level only. Enforced by a dedicated test (P3-T6).
- [ ] structlog with contextvars binding (per-request + per-intent correlation IDs); no %-style stdlib logging.
- [ ] Modern typing throughout: PEP 695 generics/`type` aliases, `X | None`, builtin generics, `Self`, `override`.

**Frontend (Bun / Svelte 5 / SvelteKit 2)**

- [ ] Bun only (`bun install`, `bun add`, `bun --bun run dev`) — never npm/pnpm; commit `bun.lock`; no `dotenv`/`ts-node`/`jest`.
- [ ] Runes only: `$state`/`$derived`/`$effect`/`$props`/`$bindable`; **no** `export let`, `$:`, stores-for-app-state, `on:click`, slots, or `createEventDispatcher`. Shared state in `.svelte.ts` modules with getter accessors.
- [ ] `$app/state` (never `$app/stores`); snippets + `{@render}`; `{@attach}` over `use:` for new element-lifecycle code; callback props for child→parent.
- [ ] UnoCSS `presetWind4` via `uno.config.ts` — no `tailwind.config.js` for styling, no PostCSS, no `@tailwind` directives (the empty `tailwind.config.js` exists solely to satisfy the shadcn-svelte CLI, per rules doc Path A).
- [ ] shadcn-svelte components are copy-in under `src/lib/components/ui` and owned/edited in-repo; `cn()` = clsx + tailwind-merge; `mode-watcher` mounted in the root layout (no theme logic in `onMount`).
- [ ] Quality gates per change: `svelte-check`, `eslint`, `bun test`, `vite build` — all green.

**Both**

- [ ] Modular layout per PRD §2.2: each bounded area is a package/module with its own controllers|routes, services, repositories, schemas|types; cross-feature access only through public module interfaces.
- [ ] Every endpoint appears in OpenAPI with typed schemas; the UI consumes only `/api/v1`.
- [ ] Secrets never logged, never returned in plaintext after write, masked in UI.

---

## Phase 0 — Repository, tooling & scaffolding (pre-M0)

### P0-T1 · Monorepo scaffold
- [ ] Create repository layout:
  ```
  perevoditarr/
  ├─ .augment/rules/            # backend-dev-pro.md, frontend-dev-pro.md (copied in, versioned)
  ├─ backend/
  │  ├─ pyproject.toml  uv.lock
  │  ├─ src/perevoditarr/
  │  │  ├─ app.py               # Litestar app factory
  │  │  ├─ cli.py               # admin CLI entrypoints (user create, doctor run, resync)
  │  │  ├─ core/                # config, db, logging, errors, security, sse bus
  │  │  └─ modules/
  │  │     ├─ auth/  instances/  mirror/  policy/  intents/  dispatch/
  │  │     ├─ rails/  doctor/  telemetry/  notifications/  stats/
  │  │     └─ integrations/     # bazarr/, lingarr/, apprise/, tautulli/, plex/, jellyfin/
  │  ├─ migrations/             # Alembic (async template)
  │  └─ tests/                  # unit/, integration/, simulators/
  ├─ frontend/
  │  ├─ package.json  bun.lock  bunfig.toml
  │  ├─ uno.config.ts  svelte.config.js  vite.config.ts  tsconfig.json
  │  ├─ tailwind.config.js      # intentionally empty — shadcn CLI shim only
  │  ├─ components.json
  │  └─ src/ (routes/, lib/{api,components/ui,features,state}/, hooks.*, app.d.ts)
  ├─ docker/                    # Dockerfile(s), compose examples
  ├─ docs/                      # PRD, tech design docs, ADRs
  └─ .github/workflows/
  ```
- [ ] Copy the two rules files into `.augment/rules/` and reference them from `CONTRIBUTING.md`.
- [ ] Add `docs/adr/` with ADR-0001 (reconciliation architecture), ADR-0002 (scheduling invariant), ADR-0003 (two-plane separation) capturing PRD §6–§7 decisions.

### P0-T2 · Backend project bootstrap
- [ ] `uv init`, `uv python pin 3.14`, `requires-python = ">=3.14"`.
- [ ] `uv add litestar granian litestar-granian msgspec "sqlalchemy[asyncio]" asyncpg aiosqlite advanced-alchemy alembic structlog httpx apprise authlib argon2-cffi cryptography python-socketio pysignalr`.
- [ ] `uv add --dev ruff basedpyright pytest pytest-asyncio polyfactory respx`.
- [ ] Configure `[tool.ruff]` (line-length 88, `select = ["E","F","I","UP","B","SIM","C4","ASYNC","RUF"]`, isort first-party `perevoditarr`) and `[tool.ruff.format]` per rules doc.
- [ ] Configure `[tool.basedpyright]` (`pythonVersion = "3.14"`, `typeCheckingMode = "recommended"`, include `src`+`tests`).
- [ ] Minimal `Litestar` app factory with `GranianPlugin`; `/api/v1/health` handler; verify `uv run litestar run --reload` boots.
- [ ] Pre-commit hooks: `ruff-check --fix`, `ruff-format`.

### P0-T3 · Frontend project bootstrap
- [ ] Scaffold SvelteKit 2 + Svelte 5 with Bun; TS strict, `moduleResolution: "bundler"`, `verbatimModuleSyntax`.
- [ ] Adapter: `@sveltejs/adapter-static` with `fallback: 'index.html'`; root layout `export const ssr = false; export const prerender = false;` (SPA served same-origin by the backend — deployment-target-appropriate per rules doc's adapter table; document rationale in ADR-0004).
- [ ] UnoCSS Path A per rules doc: `bun add -d unocss @unocss/preset-wind4 unocss-preset-animations unocss-preset-shadcn @unocss/extractor-svelte` + `bun add bits-ui @lucide/svelte tailwind-variants clsx tailwind-merge mode-watcher svelte-sonner`.
- [ ] `uno.config.ts`: `presetWind4()`, `presetAnimations()`, `presetShadcn(...)`, `extractorSvelte()`, transformers (variant-group), **widened content pipeline** to scan `src/**/*.{js,ts}` for generated theme classes.
- [ ] Empty `tailwind.config.js` + manual `components.json` + `cn()` util; add first components via `bunx shadcn-svelte@latest add button card input table dialog dropdown-menu badge tabs sonner`.
- [ ] Root layout: `virtual:uno.css` import + `<ModeWatcher />`; theme toggle wired to `mode-watcher`.
- [ ] `vite.config.ts`: `UnoCSS()` **before** `sveltekit()`; dev proxy `/api` + `/sse` → `http://localhost:8000`.
- [ ] Scripts: `"dev": "bun --bun vite dev"`, build/preview/check/test/lint/format; eslint flat config + prettier-plugin-svelte per rules doc.
- [ ] `bun:test` wiring incl. happy-dom preload (`bunfig.toml [test] preload`) for component tests; smoke test for a `.svelte.ts` module.
- [ ] `bunfig.toml` `[install] minimumReleaseAge` supply-chain hardening per rules doc.

### P0-T4 · CI & container skeleton
- [ ] GitHub Actions — backend job: `uv sync --frozen`, `ruff check`, `ruff format --check`, `basedpyright`, `pytest`.
- [ ] Frontend job: `bun install --frozen-lockfile`, `svelte-check`, `eslint`, `bun test`, `bun --bun vite build`.
- [ ] Docker: multi-stage build (Bun build of SPA → uv-based Python image; Litestar serves `/api/v1`, `/schema`, SSE, and the SPA static files with fallback). Multi-arch (amd64/arm64). Compose examples: postgres-backed and sqlite-backed.
- [ ] CI docker-build job (no push) to keep the image honest from day one.

**Phase 0 exit:** empty-but-real app boots in Docker; both CI pipelines green; a `hello` API route renders data in the SPA shell through the dev proxy.

---

## Phase 1 — M0 Observer

### P1-T1 · Core backend infrastructure
- [ ] Typed app settings: msgspec `Struct` loaded from env (DB URL, bind, secret key, log level, trusted proxies); fail-fast validation at boot.
- [ ] `SQLAlchemyPlugin` with `SQLAlchemyAsyncConfig` (asyncpg default; aiosqlite honored when configured), `AsyncSessionConfig(expire_on_commit=False)`, `create_all=False`.
- [ ] Declarative base on Advanced Alchemy (`UUIDAuditBase`; decide `UUIDv7AuditBase` for append-heavy tables — mirror rows, `intent_event` — in tech design; record in ADR-0005) with **naming conventions on `MetaData`** per rules doc; `AsyncAttrs` mixin; repo-wide `lazy="raise"` default.
- [ ] Alembic `init -t async`; import all model modules in `env.py`; first migration; verify SQLite + Postgres both migrate cleanly in CI (matrix).
- [ ] `StructlogPlugin` + JSON renderer in prod / console in dev; contextvars middleware binding `request_id`; error-handler mapping domain exceptions → typed problem responses.
- [ ] Lifespan: create/close shared `httpx.AsyncClient`s (per registered instance, pooled; explicit `Timeout` + `Limits`; **retries disabled** — assert `AsyncHTTPTransport(retries=0)`).
- [ ] Core SSE bus (`core/sse.py`): in-process pub/sub → Litestar `ServerSentEvent` endpoint `/api/v1/events` with topic filtering; heartbeat; used by all later modules.
- [ ] `OpenAPIConfig` (title/version, `ScalarRenderPlugin`); global DTO/rename policy: `rename_strategy="camel"` at the DTO layer so the TS client sees camelCase.

### P1-T2 · Auth module (FR-A1–A3, A5; FR-API3)
- [ ] Models: `user`, `api_key` (hashed), `auth_provider_config`; Argon2id password hashing (`argon2-cffi`).
- [ ] Session auth via `litestar.security.jwt` `JWTCookieAuth` (`retrieve_user_handler`, exclusions for `/login`, `/setup`, `/schema`, static); CSRF config for cookie flows.
- [ ] First-run setup flow: no users ⇒ API exposes only `/api/v1/setup`; creates initial admin.
- [ ] API-key guard for programmatic access (header), same authorization model as sessions.
- [ ] OIDC (Authlib): discovery, auth-code + PKCE, user provisioning/linking; tested against Authentik and Authelia configs (documented fixtures).
- [ ] Forward-auth mode: trusted-proxy CIDR allowlist + `Remote-User`(/`Remote-Email`) header mapping; hard-fail if enabled without trusted proxies configured.
- [ ] Secrets-at-rest encryption utility (`cryptography`, key from env) used by instance credentials and provider configs; masked serialization (write-only fields via `dto_field("private")` / dedicated write structs).
- [ ] Tests: login/refresh/logout, API-key auth, forward-auth spoof rejection, OIDC callback (mocked IdP), setup-flow lockout.

### P1-T3 · Bazarr & Lingarr API clients (`modules/integrations/…`)
- [ ] Typed msgspec response structs for every consumed endpoint (PRD Appendix A); decode at the boundary with `forbid_unknown_fields=False` (tolerate additive upstream changes), constraints where meaningful.
- [ ] Bazarr client: system status/settings, languages profiles, episodes/movies (+wanted, paged), history (episodes/movies), `PATCH /api/subtitles` translate, system jobs; `X-API-KEY` auth.
- [ ] **Version gate**: parse Bazarr version, enforce `>= 1.5.6` with typed rejection error (FR-I1).
- [ ] **Capability probe** (PRD §6.6): per-instance capability record (e.g. `translate_returns_job_id: false`, `lingarr_receives_episode_id: false` — both false today by design); probed on registration + periodic re-check; stored, surfaced in doctor (FR-DR10).
- [ ] Lingarr client: settings (`GET /api/setting/{key}`, `POST /api/setting/multiple/get` for the doctor's key set incl. `automation_enabled`, service/type/batch/retry/validation keys), translation requests (active/list/detail/cancel/retry/resume/remove), schedule jobs, statistics; `X-Api-Key` auth; version gate against the pinned line (resolve PRD open question #2 here — pin and record).
- [ ] Lingarr **auto-discovery** from Bazarr settings (`translator_type`, `lingarr_url`, `lingarr_token`) with confirmation flow (FR-I2).
- [ ] Contract tests against the simulators (P1-T8) for every consumed endpoint.

### P1-T4 · Instances module (FR-I1–I5)
- [ ] Models: `bazarr_instance`, `lingarr_instance` (N:1 allowed), encrypted credentials, capability + health snapshot columns.
- [ ] Repository/service via `SQLAlchemyAsyncRepository`/`SQLAlchemyAsyncRepositoryService`; controller CRUD with connection-test endpoint (dry validation before persist).
- [ ] Health monitor task: reachability, latency, version drift, Bazarr queue depth; snapshots persisted; SSE `instances.health` events.
- [ ] Per-instance enable/disable flag (dispatch-relevant later).

### P1-T5 · Library mirror module (FR-M1–M4)
- [ ] Models: `series`, `episode`, `movie`, `subtitle`, `wanted_subtitle` — instance-scoped, composite indexes designed for the browser's filter/sort paths (coverage per language, title search, recency) at 100k+/300k+ scale (NFR-2/NFR-4).
- [ ] Sync engine: full resync + incremental scheduled sync (configurable interval); upsert via PostgreSQL `on_conflict_do_update` with dialect-portable fallback; batched pages; per-run `sync_run` record with counters and duration.
- [ ] Wanted-list sync as its own fast loop (drives discovery later).
- [ ] Freshness tracking per instance + doctor hook (FR-M4/FR-DR11); SSE `mirror.sync` progress events.
- [ ] Performance harness: seeded synthetic library (100k episodes) in CI-nightly; assert browse query budgets (NFR-4) on Postgres.

### P1-T6 · Doctor v1 (FR-DR1–DR11, read-only)
- [ ] Check framework: `DoctorCheck` protocol (id, severity, target scope, `run() -> Finding[]`), registry per module, `doctor_run`/`doctor_finding` persistence, on-demand + scheduled + contextual triggers.
- [ ] Implement FR-DR1…FR-DR11 checks (each with explanation + fix-guidance strings; severity mapping per PRD).
- [ ] Doctor API: run, latest results, per-instance filtering; SSE completion events.
- [ ] Unit tests per check with simulator-driven misconfiguration fixtures (e.g. `automation_enabled=true`, missing upgrade setting, target language absent from profiles).

### P1-T7 · API v1 surface & TS client
- [ ] Routers: `/api/v1/{auth,setup,instances,mirror,doctor,events,system}`; consistent pagination envelope (msgspec generic `Page[T]` via PEP 695).
- [ ] OpenAPI polish: tags, operation ids, examples.
- [ ] Frontend type generation: `openapi-typescript` from `/schema/openapi.json` into `src/lib/api/types.gen.ts` + thin typed fetch wrapper (`src/lib/api/client.ts`) with auth handling; regeneration script + CI drift check.

### P1-T8 · Test simulators (foundational for all later phases)
- [ ] **Bazarr simulator**: in-process ASGI app (Litestar) implementing the consumed surface with researched semantics — async translate PATCH (204, no job id), in-memory jobs queue with `concurrent_jobs`, failed/completed caps of 10, wanted/metadata/history/settings/language-profiles, Socket.IO-compatible event emission stub.
- [ ] **Lingarr simulator**: settings store, translation-request lifecycle, **faithful §6.4 dedup semantics (empty-array on duplicate active identity)** and **§6.5 identity coarseness (series-id-as-arrMediaId, show-title-only)** — these two behaviors are the point of the simulator.
- [ ] Scenario DSL for tests: seed library, advance time, flip settings, inject failures.
- [ ] Simulators packaged for reuse in backend integration tests and (later) frontend e2e.

### P1-T9 · Frontend M0
- [ ] App shell: nav, auth guard (`+layout` load against session), login page (built-in + OIDC button + forward-auth passthrough), first-run setup wizard.
- [ ] Shared state modules (`src/lib/state/*.svelte.ts`): session, instances, SSE connection manager (auto-reconnect, topic subscription) — runes classes with getter accessors per rules doc.
- [ ] **Dashboard** (FR-U1, read-only scope): instance health cards, coverage-per-language, mirror freshness, doctor summary; live via SSE.
- [ ] **Library browser** (FR-U4 read-only scope): virtualized/paginated tables (mirror-backed), filters (language coverage, missing target, title search), series → episodes drill-down; movie list.
- [ ] **Instances settings**: register/edit/test Bazarr, confirm auto-discovered Lingarr, health detail.
- [ ] **Doctor panel**: run + results grouped by severity with fix guidance.
- [ ] Component tests for state modules (`bun:test`) and critical components (happy-dom + testing-library).

**Phase 1 / M0 exit (PRD):** register instances (version-gated), browse a 100k-episode mirror smoothly, truthful doctor report, working auth (built-in + OIDC + forward-auth) — zero write actions toward the ecosystem. Quality gates + nightly perf harness green.

---

## Phase 2 — M1 Planner (dry-run)

### P2-T1 · Policy module (FR-P1–P5, §8)
- [ ] Models: `preset`, `translation_profile`, `profile_assignment` (instance/library/series/movie scopes), `exclusion`, `override`; seed migrations for the four shipped presets (**Observe** default-active on install).
- [ ] **Cascade resolver**: pure, well-tested function `(item, layers) -> EffectivePolicy` returning every effective value **with provenance** (layer + source id) — the single source of truth reused by discovery, dispatch, UI, and doctor.
- [ ] Profile semantics: target languages, ordered source preferences, HI/forced source+target rules, grace periods (movie/show), skip conditions (embedded-track option, unmonitored, exclusions/tags).
- [ ] Validation hooks: targets vs. Bazarr language profiles; pairs vs. Lingarr `source_languages`/`target_languages`; §6.3 code-conversion cases (`zh/zt/pb`) — wired into doctor (FR-DR4/DR6) and inline into profile-editor API responses.
- [ ] Preset fork/duplicate; JSON export/import with schema-versioned msgspec struct + validation (FR-U6/§8.3).
- [ ] Property-style tests on the resolver (override wins, provenance correctness, layer removal fallback).

### P2-T2 · Intent ledger (FR-R1, FR-V1–V3 groundwork)
- [ ] Models: `intent` (natural key unique: instance, media ref, target lang, forced, hi; state; lease; priority; decision-trace ref), `intent_event` (append-only; actor, transition, reason, evidence snapshot).
- [ ] State machine implementation as an explicit transition table (`discovered → eligible → dispatched → converged | superseded | failed → retry-eligible | quarantined`); illegal transitions raise; every transition writes an `intent_event`.
- [ ] **Decision trace** structure (msgspec tagged union of rule-step records) rendered human-readable ("profile *Anime* → missing `da` → source `en` over `ja` by preference → grace passed → priority 3").
- [ ] Repository queries tuned for: backlog by priority, in-flight by instance, per-series in-flight lookup (invariant support), history filters.

### P2-T3 · Discovery engine (FR-P1)
- [ ] Wanted-mirror → candidate generation joined with cascade resolver; source-subtitle election per preference order; grace-period and skip-condition evaluation.
- [ ] Idempotent upsert into ledger keyed on natural identity (re-discovery updates, never duplicates); disappearance from wanted ⇒ candidate withdrawal/supersede path.
- [ ] Scheduled + on-sync-completion triggers; SSE `intents.discovered` events.
- [ ] Tests: language matching incl. code2 edge cases; HI/forced permutations; grace boundaries; exclusion layers.

### P2-T4 · Reconciler in Observe mode (FR-R2–R4 foundations)
- [ ] Evidence collectors: Bazarr metadata (subtitle presence), Bazarr history (action = 6 within window), Lingarr request lookup at §6.5 granularity — each a typed, independently testable component.
- [ ] Reconciliation loop (scheduled + event-nudged): advances `discovered/eligible` bookkeeping and detects `superseded` (subtitle appeared by other means) — **no dispatch exists yet**, so Observe mode is total.
- [ ] Startup re-observation routine (crash-safety skeleton, exercised fully in Phase 3).

### P2-T5 · Prioritization & plan preview (FR-Q4, FR-U3)
- [ ] Priority scorer: recency (added/aired), monitored, continuing vs. ended, movie/episode weights — configurable per profile; manual bump field.
- [ ] Volume/budget estimator: characters/lines per intent from rolling actuals (Lingarr statistics + own history once available) with runtime-based heuristic fallback; conservative (high) estimates per PRD risk table.
- [ ] Plan-preview API: "next N under current rails/caps, with reasons and cost estimate" — pure function over ledger + policy + rail config (rails simulated in Observe).
- [ ] Determinism tests: same inputs ⇒ same plan; scorer weight changes reflected with provenance.

### P2-T6 · Frontend M1
- [ ] **Profiles & presets UI**: cascade editor with provenance chips ("inherited from *Balanced* — override?"), per-layer override toggles, validation feedback inline; preset fork/import/export.
- [ ] **Plan preview** (primary Observe surface): what-would-run list with decision traces, estimated volume/budget, grouping by instance/profile.
- [ ] **History/audit UI** (FR-V2 read scope): filterable intent history with trace drill-in.
- [ ] **Library browser additions**: per-item effective-policy inspector, exclusion & profile-assignment actions, "why is this not planned?" explainer (resolver-driven).
- [ ] Superforms (or equivalent runes-native form handling per rules doc) for the profile editor's nested forms; `bun:test` coverage on cascade-display logic.

**Phase 2 / M1 exit (PRD):** plan preview is accurate and fully explainable against a real (or simulator-seeded 100k) library; presets/profiles round-trip via export/import; still zero dispatches.

---

## Phase 3 — M2 Orchestrator

### P3-T1 · Rails subsystem (§8.4; FR-Q3)
- [ ] Persisted `rail_state`: volume-cap counters (hour/day/week; per instance + global), budget counters, pause flags, breaker states — all restart-safe.
- [ ] Scheduling windows (cron-like) per instance/profile.
- [ ] Circuit breaker per (Bazarr instance, Lingarr) pair: consecutive-failure trip, half-open probe interval, auto-close; state transitions emit events + notifications.
- [ ] Rail evaluation API returning *explained* verdicts ("blocked: daily cap 200/200, resets 06:12") — consumed by dispatcher, plan preview, dashboard gauges.
- [ ] Unit tests incl. counter rollover, timezone handling for windows, breaker half-open races.

### P3-T2 · Dispatcher (FR-Q1–Q3, Q6; §6.5, §7.2)
- [ ] Bounded window per instance (default K=2; per-instance override) with headroom rule vs. `concurrent_jobs`.
- [ ] **Scheduling invariant enforcement** (non-configurable): slot admission checks per (instance, series, src→tgt) / (instance, movie, src→tgt) via ledger in-flight index; concurrency-safe (DB-level uniqueness or advisory locking — decide in tech design, record ADR-0006).
- [ ] **Pre-dispatch guard** (FR-Q2): re-verify still-wanted (fresh Bazarr call) **and** no matching active Lingarr request at §6.5 granularity; guard failures reroute intent (supersede/park) with trace.
- [ ] Backpressure: Bazarr jobs-API depth check before top-up (threshold configurable).
- [ ] Dispatch action: translate PATCH (code2 params: action/language/path/type/id/forced/hi/original_format), stamp lease, transition to `dispatched`; SSE `intents.dispatched`.
- [ ] Top-up loop reacting to slot frees (convergence/failure) and rail unblocks.

### P3-T3 · Verification & failure handling (FR-R2–R5, §7.4)
- [ ] Convergence detector: metadata presence + history action-6 within lease ⇒ `converged`; presence without our-window translation entry ⇒ `superseded` (budget/stats classified separately, FR-V3).
- [ ] Lingarr failure fast-path: request Failed/Cancelled ⇒ immediate `failed` with reason.
- [ ] Lease-expiry pipeline: verify ⇒ classify (transient/environmental/provider/poison) ⇒ retry-eligible (intent-level backoff, max attempts) | needs-attention | breaker feed | quarantine.
- [ ] Quarantine store + APIs (release/retry/exclude); needs-attention surfacing.
- [ ] **Crash-safety suite**: kill/restart mid-flight scenarios against simulators — assert retroactive convergence, no duplicate dispatches, invariant preserved (PRD success metric 5).
- [ ] **Corruption-trap unreachability suite**: adversarial scenarios (two episodes same show+pair queued, races with external actors, restart storms) against the faithful Lingarr simulator — assert the §6.4 empty-array path is never triggered by Perevoditarr traffic (PRD success metric 1).

### P3-T4 · Telemetry plane (NFR-7; §7.3)
- [ ] Bazarr Socket.IO client consumer (python-socketio): jobs/series/episode/movie events → internal event bus; fuzzy job correlation (name/path/window) **flagged telemetry-only** in types so it cannot feed the state machine (enforce via module boundary + lint/import test).
- [ ] Lingarr SignalR consumers (pysignalr): TranslationRequestsHub + JobProgressHub → progress events at §6.5 granularity mapped to the single in-flight intent.
- [ ] Connection lifecycle: retry/backoff, health status per stream, **automatic degradation to polling** (jobs API / active-requests polling) with seamless upgrade when sockets return.
- [ ] Bridge to UI SSE topics (`telemetry.*`); nudge hooks into reconciler (event-triggered re-observation — nudges only, never transitions).

### P3-T5 · Notifications (FR-X1)
- [ ] Apprise integration: `notification_route` model (URLs encrypted), per-event routing matrix (breaker trip/close, caps reached, quarantine additions, doctor criticals, daily digest), test-fire endpoint.
- [ ] Digest job (scheduled): converged/superseded/failed counts, spend estimate vs. actuals, notable findings.
- [ ] Rate-limit notification spam (coalescing window per event type).

### P3-T6 · Hardening & guards
- [ ] Transport-retry ban test: assert every outbound client transport has retries disabled (FR-DR9 self-check + CI test).
- [ ] Doctor additions: rails misconfig sanity (K vs. `concurrent_jobs` live check), telemetry stream health, breaker state surfacing.
- [ ] Load test: sustained dispatch against simulators at scale; verify NFR-4 UI budgets hold during heavy reconciliation.
- [ ] Optional nightly e2e workflow against real `bazarr:v1.5.6` + pinned Lingarr containers (compose harness; smoke path: register → discover → dry-run → single real dispatch on a fixture library).

### P3-T7 · Frontend M2
- [ ] **Queue view** (FR-U2): backlog (priority-ordered, bump-to-front), in-flight with live progress bars (telemetry SSE), needs-attention + quarantine tabs with actions, per-instance grouping.
- [ ] **Rails gauges** on dashboard + queue: live cap/budget/window/breaker states with explanations; global + per-instance pause/resume controls (persisted).
- [ ] **Activation flow**: explicit Observe → Active transition per instance/profile with confirmation summarizing rails in force (safe-by-default UX).
- [ ] Notification settings UI with per-event routing and test button.
- [ ] Live-degradation indicator (websocket vs. polling telemetry) in the status bar.

**Phase 3 / M2 exit (PRD):** end-to-end automated translation on a real stack; rails demonstrably enforced; corruption-trap and crash-safety suites green; notifications firing.

---

## Phase 4 — M3 Insight & polish

### P4-T1 · Statistics & budget reconciliation (FR-U8)
- [ ] Stats module: throughput, durations, failure rates by class, converged vs. superseded, per-language coverage trends; efficient rollup tables (avoid heavy aggregate queries at request time).
- [ ] Budget reconciliation: periodic pull of Lingarr statistics; estimates vs. actuals correction feeding the estimator (P2-T5) and budget rails.
- [ ] Stats API + dashboard charts (frontend charting per shadcn/uno-compatible lib chosen in tech design).

### P4-T2 · Timelines & pass-through (FR-V4, FR-X3)
- [ ] Per-item timeline API stitching intent events + Lingarr request states + Bazarr history; timeline UI on item detail.
- [ ] Lingarr pass-through actions in UI (cancel/retry/resume/remove) mapped 1:1, clearly labeled as acting on Lingarr; audit-logged.

### P4-T3 · Operability & release
- [ ] Prometheus-style metrics endpoint (NFR-6): intents by state, dispatch rates, rail states, sync durations, stream health.
- [ ] Admin CLI polish (`perevoditarr` entrypoints: create-user, run-doctor, resync, export-config).
- [ ] Docs site content: install (compose for Postgres + SQLite), onboarding walkthrough (Observe → plan → activate), preset sharing guide, doctor reference, API guide (Scalar link), troubleshooting (incl. Lingarr-automation conflict explainer).
- [ ] Release engineering: versioned images (ghcr), changelog automation, SQLite ceiling guidance from perf data (resolves PRD open question #4).
- [ ] v1.0 release checklist: PRD success metrics 1–6 verified and recorded.

---

## Phase 5 — M4 Watch-aware & extended auth

### P5-T1 · Watch integrations (FR-X2, FR-Q5)
- [ ] `watch_source` framework + score cache with TTL; scorer input plugged into P2-T5 weights.
- [ ] Tautulli client (watch history/popularity), Plex client (history + watchlist), Jellyfin client (playback data) — each optional, independent, doctor-checked, encrypted credentials.
- [ ] UI: integration settings, watch-boost visibility in plan preview traces ("+2 priority: watched this week (Tautulli)").

### P5-T2 · Extended auth & roles (FR-A4, FR-A6)
- [ ] LDAP bind authentication provider.
- [ ] Roles: admin vs. viewer enforced via Litestar guards across API + UI; scope PRD open question #3 (per-instance permissions) with an ADR before implementing.

### P5-T3 · Webhook ingestion (FR-X4)
- [ ] Inbound webhook endpoints (Bazarr/Sonarr notification targets) as discovery/sync triggers; secret-token validation; dedup with polling-sourced discovery.

---

## Cross-phase tracking

- [ ] ADR log maintained for every architectural decision flagged above (0001–0006+).
- [ ] Capability-detection slots re-verified against each new upstream Bazarr/Lingarr release (no feature may start depending on unmerged upstream changes — PRD §2.4).
- [ ] Simulators updated whenever upstream pinned versions move; contract tests are the tripwire.
- [ ] Each phase closes with: quality gates green (Conventions §0), phase exit criterion demoed, docs updated, and a tagged pre-release.

