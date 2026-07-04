# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Perevoditarr is a self-hosted orchestration/observability layer between Bazarr and Lingarr: a declarative reconciliation engine that drives subtitle translation through Bazarr's translate API behind hard safety rails (dispatch windows, volume caps, budgets, circuit breakers, quarantine). Monorepo with two packages: `backend/` (Python 3.14 — Litestar + Granian + msgspec + SQLAlchemy async/Advanced Alchemy, managed with **uv**) and `frontend/` (SvelteKit 2 + Svelte 5 runes SPA — **Bun** runtime/PM/test-runner, UnoCSS presetWind4 + shadcn-svelte, Biome). Never use pip/poetry/black/flake8 or npm/pnpm/jest/prettier/eslint.

**Before writing code, read the matching guideline file** — they are the canonical stack reference and correct the most common wrong-but-plausible habits (FastAPI/Pydantic reflexes on the backend; Svelte 4/React/Tailwind-config reflexes on the frontend):

- `.augment/rules/backend-dev-pro.md` — Litestar/msgspec/SQLAlchemy-async idioms.
- `.augment/rules/frontend-dev-pro.md` — Bun/Svelte 5/SvelteKit 2/UnoCSS/shadcn-svelte idioms.

## Commands

Full stack (repo root): `cp .env.example .env` once, then `scripts/start.sh` (installs deps, runs `alembic upgrade head`, starts backend + frontend; flags: `--backend-only`, `--frontend-only`, `--no-install`, `--no-migrate`).

Backend — run from `backend/` (or repo root via `uv run --directory backend <cmd>`):

```bash
uv run pytest                                  # full suite (unit + integration)
uv run pytest tests/unit/test_rails_windows.py # one file
uv run pytest tests/unit/test_errors.py::test_name  # one test
uv run ruff format && uv run ruff check --fix  # format + lint
uv run basedpyright                            # type check (warnings are failures)
uv run alembic upgrade head                    # apply migrations
uv run alembic revision --autogenerate -m "…"  # new migration
uv run perevoditarr create-user --username admin  # also: export-openapi, run-doctor, resync, export-config
```

Frontend — run from `frontend/`:

```bash
bun install
bun run dev                                    # Vite dev server, proxies /api and /sse to backend
bun run build                                  # static SPA build (adapter-static)
bun run lint                                   # biome check .
bun run format                                 # biome check --write .
bun run check                                  # svelte-check (the type gate)
bun test --conditions browser                  # all tests (happy-dom preloads from bunfig.toml)
bun test --conditions browser src/lib/policy-display.test.ts   # one file
bun test --conditions browser -t 'name pattern'                # by test name
bun run generate:api                           # regenerate src/lib/api/types.gen.ts from backend OpenAPI
```

Pre-commit hooks live in `prek.toml` (prek, not pre-commit): ruff/basedpyright path-scoped to `^backend/`, biome/svelte-check to `^frontend/`, gitleaks, Conventional Commit messages enforced, and **commits directly to `main` are blocked**.

## Architecture

- **Backend entry**: `backend/src/perevoditarr/app.py` — `create_app()` is the composition root. Admin CLI (`perevoditarr …`) is `backend/src/perevoditarr/cli.py`. Settings come from `PEREVODITARR_*` env vars via `core/settings.py`; the root `.env` is shared by backend, Vite proxy, and `scripts/start.sh` (`backend/.env` overrides it; see `.env.example` for every knob).
- **Vertical slices**: `backend/src/perevoditarr/modules/<name>/` each own `controllers.py`, `service.py`, `repository.py`, `models.py`, `schemas.py` (msgspec `ApiStruct` DTOs). Shared infra lives in `core/` (db, http, sse, metrics, errors, security, logging).
- **Two planes, never mixed**: the correctness plane (`modules/intents`, `modules/dispatch`, `modules/rails`) derives all state transitions from durable evidence and must never import `modules/telemetry`; telemetry is ephemeral and must never import the intent state machine. Enforced by `backend/tests/unit/test_two_plane_separation.py`.
- **Persistence**: SQLAlchemy async with Advanced Alchemy base classes; Alembic migrations in `backend/migrations/`. One migration history serves both SQLite (`aiosqlite`, default) and Postgres (`asyncpg`) — new migrations must work on both.
- **Frontend**: routes in `frontend/src/routes/`; hand-written API layer in `frontend/src/lib/api/` (`client.ts`, `endpoints.ts`, `types.ts`); shadcn-svelte components in `src/lib/components/ui/`; feature components in `src/lib/features/` with co-located `*.test.ts`. Live updates arrive over the `/api/v1/events` SSE stream.

## Key workflows

**Change or add an API endpoint** (backend surface reaches the frontend through generated types):
1. Implement handler in the module's `controllers.py`; new controllers must be registered in the `api_v1` Router list in `app.py`.
2. From `frontend/`: `bun run generate:api` to refresh `src/lib/api/types.gen.ts`, then wire a wrapper in `src/lib/api/endpoints.ts`.
3. Verify: `uv run pytest` (backend) and `bun run check` (frontend).

**Add or change an ORM model**:
1. Edit the module's `models.py`, then import the model in the aggregate `backend/src/perevoditarr/models.py` (Alembic's `env.py` only sees metadata registered there).
2. `uv run alembic revision --autogenerate -m "…"` from `backend/`, review the script for SQLite + Postgres compatibility, then `uv run alembic upgrade head`.
3. Every relationship must declare an async-safe loading strategy (`lazy="raise"` guard, `selectin`/`joined` for deliberate eager loads) — `test_db_conventions.py` fails otherwise.

**Backend tests**: `tests/unit/` for pure logic; `tests/integration/` uses the `client` TestClient fixture from `tests/conftest.py` (call `complete_setup(client)` to pass the first-run gate, `csrf_headers(client)` for mutating requests) and the Bazarr/Lingarr simulators in `tests/simulators/`.

## Repository-specific rules

- **Typing gate is load-bearing**: `[tool.basedpyright]` in `backend/pyproject.toml` must never gain global diagnostic overrides, baselines, `pyrightconfig.json`, or file-level pragmas — `tools/check_basedpyright_config.py` (hook + CI gate) rejects them. The only sanctioned suppression is a single-line `# pyright: ignore[ruleName]` with a short justification.
- **Transport-retry ban**: never enable httpx transport retries; use `build_transport()` / `HttpClientRegistry` from `core/http.py` (pinned `retries=0`). Bazarr already retries 3× toward Lingarr; retry semantics live at the intent level only. Enforced by `test_transport_retry_ban.py`.
- Use msgspec `Struct`s (`ApiStruct` in `core/schemas.py`), not Pydantic; ORM model modules must not use `from __future__ import annotations`.
- Rail/budget usage is **counted from `intent_event` audit rows**, never accumulated in mutable counters (restart-safe by construction) — follow this pattern for anything usage- or evidence-shaped (see `modules/rails/repository.py`).
- `frontend/src/lib/api/types.gen.ts` is generated — never hand-edit; run `bun run generate:api`.
- Svelte 5 runes only: no `export let`, `$:`, stores, `on:click`, or `$app/stores` (use `$app/state`). Styling goes through `uno.config.ts` (presetWind4 + presetShadcn) and theme vars in `src/app.css` — do not add Tailwind/PostCSS config.
- Safe-by-default is a product invariant: instances dispatch only after explicit activation; keep new features read-only/inactive until explicitly enabled.
- Commit messages follow Conventional Commits; work on a branch (the prek hook blocks committing to `main`).
