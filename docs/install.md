# Installation

Perevoditarr ships as a single container image that runs database migrations and then
serves `/api/v1`, the OpenAPI schema at `/schema`, the SSE event stream, and the built
SPA (same-origin, with an `index.html` fallback). It requires network access to your
Bazarr and Lingarr APIs only; it never mounts media volumes.

The container image (`docker/Dockerfile`) is a multi-stage, multi-arch (amd64/arm64)
build: Bun builds the static SPA, `uv` builds the Python backend, and the runtime
stage runs as a non-root `perevoditarr` user, exposes port `8000`, and on start runs
`alembic upgrade head` before launching Litestar. The image sets `PEREVODITARR_SPA_DIR`
to the bundled SPA, so you do not configure it yourself.

## Prerequisites

- Docker with the Compose plugin.
- A reachable Bazarr instance on **v1.5.6 or newer** with `translator_type` set to
  `lingarr`, and a reachable Lingarr instance on **1.2.4 or newer**. Older versions are
  rejected at registration.

## Choose a database engine

PostgreSQL is the default and recommended engine; SQLite is a lightweight option for
small libraries. Both compose files build the image from the repository root, so run
them from there. Only `postgresql+asyncpg://` and `sqlite+aiosqlite://` URL schemes are
accepted.

### PostgreSQL (recommended)

Uses `docker/compose.postgres.yml`, which runs Perevoditarr alongside a `postgres:18`
service with a health check and a named `pgdata` volume:

```bash
docker compose -f docker/compose.postgres.yml up -d
```

The bundled `PEREVODITARR_DATABASE_URL` points at the sidecar database:

```
postgresql+asyncpg://perevoditarr:perevoditarr@db:5432/perevoditarr
```

Change the database user, password, and database name (the `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB` variables on the `db` service and the matching parts
of `PEREVODITARR_DATABASE_URL`) before exposing the stack.

### SQLite

Uses `docker/compose.sqlite.yml`, which mounts a host `./config` directory into the
container at `/config` and stores the database file there:

```bash
docker compose -f docker/compose.sqlite.yml up -d
```

The bundled `PEREVODITARR_DATABASE_URL` is:

```
sqlite+aiosqlite:////config/perevoditarr.db
```

## Required environment

Set these before your first `prod` deployment. In production you must supply a secret
key; the app fails fast at boot without one.

- `PEREVODITARR_SECRET_KEY` — signing key for session cookies. Required when
  `PEREVODITARR_ENV=prod`, and must be at least 32 characters. Generate one with, for
  example, `openssl rand -hex 32`.
- `PEREVODITARR_DATABASE_URL` — async SQLAlchemy URL. Already set in both compose
  files; override it to point at your own database.
- `PEREVODITARR_ENV` — set to `prod` for production deployments (enables the secret-key
  requirement); defaults to `dev`.

Add these to the `environment:` block of the `perevoditarr` service, for example:

```yaml
    environment:
      PEREVODITARR_ENV: prod
      PEREVODITARR_SECRET_KEY: "replace-with-a-32+-character-random-secret"
      PEREVODITARR_DATABASE_URL: postgresql+asyncpg://perevoditarr:perevoditarr@db:5432/perevoditarr
```

## Environment reference

All settings are read from the `PEREVODITARR_` prefix; the variable name is the field
name upper-cased. Interval knobs are in seconds and set to `0` disable the respective
background loop (they must be `>= 0`); the dispatch tuning knobs must be `>= 1`.

| Variable | Default | Meaning |
|---|---|---|
| `PEREVODITARR_ENV` | `dev` | `dev` or `prod`; `prod` requires a secret key. |
| `PEREVODITARR_DATABASE_URL` | `sqlite+aiosqlite:///perevoditarr.db` | Async DB URL (`postgresql+asyncpg://` or `sqlite+aiosqlite://`). |
| `PEREVODITARR_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `PEREVODITARR_SECRET_KEY` | unset | Session signing key; required (>= 32 chars) when `ENV=prod`. |
| `PEREVODITARR_TRUSTED_PROXIES` | empty | Comma-separated CIDR allowlist for forward-auth. |
| `PEREVODITARR_SPA_DIR` | unset | Directory of the built SPA; preset by the image. |
| `PEREVODITARR_HEALTH_INTERVAL_SECONDS` | `60` | Instance health polling interval. |
| `PEREVODITARR_SYNC_INTERVAL_SECONDS` | `3600` | Library mirror sync interval. |
| `PEREVODITARR_WANTED_INTERVAL_SECONDS` | `300` | Wanted-list refresh interval. |
| `PEREVODITARR_DOCTOR_INTERVAL_SECONDS` | `86400` | Scheduled doctor run interval. |
| `PEREVODITARR_DISCOVERY_INTERVAL_SECONDS` | `900` | Policy discovery interval. |
| `PEREVODITARR_RECONCILE_INTERVAL_SECONDS` | `600` | Intent reconciliation interval. |
| `PEREVODITARR_DISPATCH_INTERVAL_SECONDS` | `120` | Dispatcher tick interval. |
| `PEREVODITARR_VERIFY_INTERVAL_SECONDS` | `180` | Convergence verification interval. |
| `PEREVODITARR_DISPATCH_LEASE_SECONDS` | `2700` | Evidence deadline after a dispatch. |
| `PEREVODITARR_DISPATCH_BACKPRESSURE_PENDING` | `10` | Bazarr pending-queue depth that holds top-up. |
| `PEREVODITARR_DISPATCH_MAX_ATTEMPTS` | `4` | Attempts before an intent is quarantined. |
| `PEREVODITARR_DISPATCH_RETRY_BASE_SECONDS` | `300` | Exponential backoff base between auto-retries. |
| `PEREVODITARR_DISPATCH_RETRY_CAP_SECONDS` | `21600` | Exponential backoff cap between auto-retries. |
| `PEREVODITARR_DIGEST_INTERVAL_SECONDS` | `86400` | Notification digest interval. |
| `PEREVODITARR_TELEMETRY_POLL_INTERVAL_SECONDS` | `30` | Telemetry polling-fallback refresh; `0` disables the telemetry plane. |
| `PEREVODITARR_STATS_ROLLUP_INTERVAL_SECONDS` | `900` | Stats rollup interval. |
| `PEREVODITARR_BUDGET_RECONCILE_INTERVAL_SECONDS` | `3600` | Budget reconciliation against Lingarr statistics. |

## First-run setup

The image runs Alembic migrations automatically on start, so you do not create the
schema yourself. When no users exist, the API exposes only the setup endpoint and the
SPA sends you to the setup page.

1. Open the app in a browser, for example `http://localhost:8000/`.
2. You are redirected to `/setup`. Create the initial admin account. This is the only
   write action available until an admin exists.
3. Sign in, then continue with the [onboarding walkthrough](onboarding.md) to register
   your Bazarr and Lingarr instances.

You can also create the first admin from the command line without the browser:

```bash
docker exec -it perevoditarr perevoditarr create-user --username admin
```

See the [operations guide](operations.md) for the full admin CLI reference.
