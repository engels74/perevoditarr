# SQLite operational guidance and library-size ceiling

This document gives operational guidance for the SQLite backend option and
states a recommended library-size ceiling above which PostgreSQL should be used.
It resolves PRD open question #4 ("SQLite operational guidance: recommended
library-size ceiling for the SQLite option, to be established empirically during
M0 performance testing").

## Summary recommendation

- PostgreSQL is the default and recommended engine (PRD NFR-2).
- SQLite (aiosqlite) is fully supported and appropriate for small to medium,
  single-instance libraries.
- Use PostgreSQL when any of the following hold:
  - the library approaches or exceeds roughly 100k episodes (NFR-2 scale),
  - multiple Perevoditarr instances or processes share one database,
  - dispatch throughput is high and sustained (large backlog draining under
    tight rails).

Both engines run the identical schema and code paths. There is no functional
difference between them; the choice is purely operational.

## Dialect portability (NFR-2)

Per NFR-2, all persistence is dialect-portable via SQLAlchemy / Advanced
Alchemy, and features must not fork on dialect. There are no SQLite-only or
Postgres-only feature branches in Perevoditarr: the same migrations, queries,
and reconciliation logic run on both. CI proves this by running the Alembic
migration matrix (`uv run alembic upgrade head` / `downgrade base` /
`upgrade head`) against both `sqlite+aiosqlite` and `postgresql+asyncpg` on
every change (`.github/workflows/ci.yml`). Switching engines is therefore a
configuration change (`PEREVODITARR_DATABASE_URL`), not a migration to a
different feature set.

Example URLs:

- SQLite: `sqlite+aiosqlite:////config/perevoditarr.db`
  (see `docker/compose.sqlite.yml`)
- PostgreSQL:
  `postgresql+asyncpg://perevoditarr:perevoditarr@db:5432/perevoditarr`
  (see `docker/compose.postgres.yml`)

## Empirical basis: the M0 perf harness

The ceiling guidance is grounded in the performance harness introduced in M0:
`backend/tests/perf/test_browse_budgets.py`
(`test_browse_query_budgets_at_100k_scale`). The harness:

- seeds 1,000 series x 100 episodes (100,000 episodes) with 200,000 subtitle
  rows and a wanted-subtitle backlog, matching NFR-2 scale;
- asserts each library-browser query completes within the NFR-4 budget of
  200 ms server time (`BUDGET_SECONDS = 0.2`);
- is gated by the `perf` pytest marker and only runs when
  `PEREVODITARR_PERF_DATABASE_URL` is set.

It runs against PostgreSQL in the nightly performance workflow
(`.github/workflows/nightly-perf.yml`), which is the engine the NFR-2/NFR-4
budgets are validated on. Run it manually against a candidate engine with:

```
cd backend
PEREVODITARR_PERF_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db \
  uv run pytest tests/perf -m perf
```

To characterize SQLite headroom on your own hardware, point
`PEREVODITARR_PERF_DATABASE_URL` at a SQLite URL and observe where browse
queries begin to approach the 200 ms budget under your representative library
shape. The same harness measures both engines because the schema and queries do
not fork on dialect.

## When SQLite is a good fit

SQLite is a reasonable choice when all of these hold:

- a single Perevoditarr process owns the database file (no shared access from
  other instances or external tools);
- the library is small to medium (well below NFR-2 scale, i.e. comfortably under
  ~100k episodes);
- dispatch volume is modest, so the reconciler, dispatcher, scheduler, and
  telemetry consumers are not contending heavily for writes at the same time.

Under those conditions SQLite keeps the deployment to a single container with no
external database service, which is the point of the lightweight option.

Operational notes for SQLite:

- Keep the database file on a local, durable filesystem (not a network share);
  the bundled compose file mounts `./config` for this.
- Only one writer process should open the database. Perevoditarr's concurrent
  scheduler/reconciler/dispatcher/telemetry components run inside one process
  and share a single connection pool, which is compatible with SQLite; running a
  second instance against the same file is not.

## When to move to PostgreSQL

Move to PostgreSQL (the recommended engine) when:

- the library approaches or exceeds ~100k episodes, where the NFR-4 browse
  budget is validated for Postgres by the perf harness above;
- more than one Perevoditarr instance or process must share the database, or you
  want managed backups, connection pooling, and concurrent access;
- sustained high dispatch throughput produces heavy concurrent write load that
  SQLite's single-writer model would serialize.

Migration is an engine switch, not a data-model change: stand up Postgres, run
`alembic upgrade head` against the new `PEREVODITARR_DATABASE_URL`, and
re-point the application. Perevoditarr never uses `create_all`; the schema is
always Alembic's responsibility.

## Status of the ceiling

The ~100k-episode figure is deliberately conservative and aligned to the NFR-2
scale target the perf harness exercises. It is guidance, not a hard limit, and
should be refined with field data: as real deployments report where SQLite
browse latency approaches the 200 ms NFR-4 budget on their hardware and library
shapes, update this document with the observed numbers. This resolves PRD open
question #4 while leaving the exact threshold open to empirical tightening.
