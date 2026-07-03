# v1.0 release checklist

This checklist gates a tagged v1.0 release of Perevoditarr. It maps every PRD
Section 13 success metric to the concrete evidence in this repository, then
mirrors the plan's Cross-phase closing checklist ("quality gates green, phase
exit criterion demoed, docs updated, and a tagged pre-release").

Nothing here is released until all boxes are checked against the exact commit
being tagged.

## Success metrics (PRD Section 13)

Each metric below states how it is verified in this repo. Automated evidence
lives under `backend/tests/`; manual evidence is recorded as a dated note in the
release PR.

### Metric 1 — Zero duplicate-induced corrupt subtitle files

- [ ] The PRD Section 6.4 empty-array corruption trap is unreachable for
      Perevoditarr traffic.
- Verified by: `backend/tests/integration/test_corruption_and_crash.py`
  (corruption-trap unreachability suite). It asserts the Section 6.5 invariant
  keeps at most one dispatch per `(instance, series, source to target)` in
  flight and the pre-dispatch guard blocks on any matching active Lingarr
  request.
- Command: `cd backend && uv run pytest tests/integration/test_corruption_and_crash.py`

### Metric 2 — Time-to-first-value under 10 minutes

- [ ] Fresh install reaches a truthful doctor report and an accurate dry-run
      plan in under 10 minutes.
- Verified by: documented manual walkthrough on a clean environment.
  1. Bring up a stack with `docker compose -f docker/compose.postgres.yml up`
     (or `docker/compose.sqlite.yml` for the lightweight option).
  2. Create the first admin user: `perevoditarr create-user --username admin`.
  3. Configure a Bazarr instance (>= v1.5.6) and a Lingarr instance
     (>= 1.2.4), then run `perevoditarr run-doctor` and confirm findings are
     truthful.
  4. Produce a dry-run plan in the UI (Observe to plan) and confirm it is
     accurate.
- Record: wall-clock elapsed time and the doctor output in the release PR.

### Metric 3 — Backlog convergence at configured rails

- [ ] Coverage grows monotonically per target language under configured caps,
      and per-day throughput matches the configured rails exactly.
- Verified by: documented manual verification over a representative library.
  1. Configure rails (per-day caps, concurrency) and a target language.
  2. Activate reconciliation and observe `GET /api/v1/stats/overview` and
     `GET /api/v1/stats/budget` across at least one full daily cycle.
  3. Confirm coverage increases monotonically and daily dispatch count equals
     the configured cap.
  4. Cross-check per-intent history via
     `GET /api/v1/intents/{id}/timeline`.
- Supporting automated evidence: rail accounting is exercised by
  `backend/tests/integration/test_rails.py` and
  `backend/tests/integration/test_dispatch_scale.py`.
- Record: the stats snapshots and the observed daily throughput in the
  release PR.

### Metric 4 — 100% explainability (complete decision trace)

- [ ] Every automated action in history carries a complete decision trace.
- Verified by: the decision-trace tests
  `backend/tests/unit/test_intent_trace.py` (trace rendering and
  encode/decode round-trip, FR-V1), backed by the append-only `intent_event`
  audit trail surfaced through `GET /api/v1/intents/{id}/timeline`.
- Command: `cd backend && uv run pytest tests/unit/test_intent_trace.py`

### Metric 5 — Crash-safety (no lost intents, no duplicates)

- [ ] A restart during heavy in-flight load loses no intents and creates no
      duplicates.
- Verified by: the crash-safety suite in
  `backend/tests/integration/test_corruption_and_crash.py`. After a simulated
  restart (fresh in-memory services over the surviving ledger), verification
  retroactively converges in-flight intents and the dispatcher never
  double-dispatches.
- Command: `cd backend && uv run pytest tests/integration/test_corruption_and_crash.py`

### Metric 6 — UI responsiveness at NFR-2 scale within NFR-4 budgets

- [ ] Library browser interactions stay under 200 ms server time at 100k+
      episode scale (NFR-4 at NFR-2 scale).
- Verified by: the load-test / perf harness
  `backend/tests/perf/test_browse_budgets.py`
  (`test_browse_query_budgets_at_100k_scale`), which seeds 1,000 series x 100
  episodes (100k episodes, 200k subtitle rows) and asserts each browse query
  stays within the 200 ms budget.
- The harness is gated by the `perf` pytest marker and requires
  `PEREVODITARR_PERF_DATABASE_URL` (Postgres, the recommended engine). It runs
  in the `nightly-perf` workflow; run it on the release candidate:
  `cd backend && PEREVODITARR_PERF_DATABASE_URL=postgresql+asyncpg://... uv run pytest tests/perf -m perf`
- Record: the passing perf run against the tagged commit.

## Quality gates

Mirror the plan's per-phase closing checklist. All gates must be green on the
tagged commit.

### Backend (`cd backend`)

- [ ] `uv run ruff check`
- [ ] `uv run ruff format --check`
- [ ] `uv run python tools/check_basedpyright_config.py` (no global typing
      ignores)
- [ ] `uv run basedpyright`
- [ ] `uv run pytest`
- [ ] `uv run alembic upgrade head` then `uv run alembic downgrade base` then
      `uv run alembic upgrade head` on both SQLite and Postgres (NFR-2 dialect
      portability)

### Frontend (`cd frontend`)

- [ ] `bun install --frozen-lockfile`
- [ ] `bun run check` (svelte-kit sync + svelte-check)
- [ ] `bun run lint` (Biome)
- [ ] `bun run test`
- [ ] `bun --bun vite build`
- [ ] `bun run generate:api` produces no diff in `src/lib/api/types.gen.ts`
      (schema drift check)

### Container

- [ ] `docker/Dockerfile` builds multi-arch (linux/amd64, linux/arm64) in CI.
- [ ] The `release` workflow publishes `ghcr.io/<owner>/perevoditarr` tagged
      with the semver tag and `latest`.

## Docs

- [ ] Install docs cover both compose files (`docker/compose.postgres.yml`,
      `docker/compose.sqlite.yml`).
- [ ] `docs/sqlite-ceiling.md` reflects the current perf findings and resolves
      PRD open question #4.
- [ ] API guide links the Scalar UI at `/schema`; metrics endpoint at
      `/metrics` documented (NFR-6).
- [ ] ADR log is current (0001 through the latest).
- [ ] This checklist is updated with the metric evidence captured for the
      release.

## Tag and release

- [ ] Update the version and finalize release notes source (conventional
      commits).
- [ ] Cut a tagged pre-release (`vX.Y.Z-rc.N`) and validate the published GHCR
      image end to end.
- [ ] All success metrics 1-6 recorded above are verified against the tagged
      commit.
- [ ] Push the final `vX.Y.Z` tag; the `release` workflow builds and pushes the
      images and creates the GitHub Release with the generated changelog.
