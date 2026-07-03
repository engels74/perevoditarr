# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Perevoditarr is a self-hosted orchestration layer that drives subtitle translation *through Bazarr's
translate API* (the single ecosystem write surface) as a declarative reconciliation engine, with
safety rails (dispatch windows, volume caps, budget ceilings, circuit breakers, quarantine). It is a
monorepo: a Python 3.14 / **Litestar** backend (`backend/`) and a **SvelteKit** static SPA
(`frontend/`). In dev, run both — the Vite dev server proxies `/api` (and the `/api/v1/events` SSE
stream) to the backend on `:8000`.

## Commands

Backend commands run from `backend/`; frontend commands from `frontend/`. From the repo root,
`uv run --project backend <cmd>` and `bun run --cwd frontend <cmd>` are equivalent.

| Task | Backend (`backend/`, uv + Python 3.14) | Frontend (`frontend/`, Bun) |
|---|---|---|
| Install | `uv sync` | `bun install` |
| Run dev | `LITESTAR_APP=perevoditarr.app:app uv run litestar run --reload` | `bun run dev` |
| Build | — | `bun run build` |
| Lint / format | `uv run ruff check --fix` / `uv run ruff format` | `bun run lint` / `bun run format` (Biome) |
| Type check | `uv run basedpyright` | `bun run check` (svelte-check) |
| All tests | `uv run pytest` | `bun run test` |
| One file | `uv run pytest tests/unit/<file>.py` | `bun test --conditions browser <file>` |
| One test | `uv run pytest tests/unit/<file>.py::<test_name>` (or `-k <name>`) | — |
| DB migrate | `uv run alembic upgrade head` | — |
| New migration | `uv run alembic revision --autogenerate -m "<msg>"` | — |

- Admin CLI: `uv run perevoditarr <cmd>` — `create-user`, `export-openapi`, `run-doctor`, `resync`,
  `export-config` (see `backend/src/perevoditarr/cli.py`).
- Regenerate frontend API types after any backend schema/route change: `bun run generate:api`
  (dumps the backend OpenAPI schema, then writes `frontend/src/lib/api/types.gen.ts`).
- Quality gates are enforced by `prek` hooks (`prek.toml`): ruff, basedpyright + config gate,
  Biome, svelte-check, gitleaks, Conventional Commits, and a **block on committing to `main`**.

## Architecture and boundaries

- **Entry point:** `backend/src/perevoditarr/app.py` — `create_app()` is the Litestar application
  factory. All controllers register on the `api_v1` `Router` (`/api/v1`), all `provide_*` DI
  functions register in the single `dependencies={}` map, and background loops run in the
  `_background_loops_lifespan`. **Wiring a new module means editing this file in three places** (see
  workflow below).
- **Backend modules:** `backend/src/perevoditarr/modules/<name>/` — each owns one domain and follows
  a fixed shape: `models.py` (SQLAlchemy), `schemas.py` (msgspec `Struct`s), `service.py`,
  `repository.py` (optional), `controllers.py` (Litestar `Controller` + `provide_*` DI functions),
  and `__init__.py` re-exporting the public surface. Modules never import each other's internals;
  cross-module coordination is wired as explicit in-process seams in `app.py` (e.g. mirror's
  wanted-sync completion hook fans out into intents — mirror never imports intents).
- **Shared infra:** `backend/src/perevoditarr/core/` — settings, db/session config, errors, metrics,
  logging, SSE bus, `HttpClientRegistry` (pooled httpx clients), locks.
- **External integrations:** `modules/integrations/<vendor>/` (`bazarr`, `lingarr`, `apprise`,
  `jellyfin`, `plex`, `tautulli`). Each is a thin client over a pooled httpx `AsyncClient`; obtained
  via `InstanceGateway` (`modules/instances/gateway.py`). Bazarr is the only write surface.
- **Domain core:** the intent ledger (`modules/intents/` — append-only `Intent` + `IntentEvent`
  audit trail with a state machine) is the source of truth. Rails usage (`modules/rails/`) and stats
  are *re-derived* from the audit trail, never accumulated in mutable counters — this is what makes
  the system restart-safe.
- **Persistence:** SQLAlchemy 2.0 async (SQLite or Postgres, same migration history). Migrations
  live in `backend/migrations/versions/`; `migrations/env.py` uses `perevoditarr.core.db.metadata`
  and imports `perevoditarr.models` to register every table.
- **Frontend:** SvelteKit with `adapter-static` (SPA, `fallback: index.html`). API calls go through
  `frontend/src/lib/api/endpoints.ts`, typed against the generated `types.gen.ts`.

## Key workflows

**Add a backend API resource / module** (missing any step ships an unreachable or untyped endpoint):
1. Add model(s) in `modules/<name>/models.py` (extend `UUIDAuditBase`; **no**
   `from __future__ import annotations` in model modules).
2. Register the model in the `perevoditarr/models.py` aggregator so Alembic autogenerate sees it.
3. Generate + review a migration: `uv run alembic revision --autogenerate -m "..."` (autogenerate
   misses some type changes — always read the script).
4. Add msgspec schemas (`schemas.py`), service (`service.py`), and a `Controller` + `provide_*`
   function (`controllers.py`); re-export from `__init__.py`.
5. In `app.py`: add the controller to the `api_v1` `route_handlers` list **and** register its
   `provide_*` in the `dependencies={}` map.
6. Regenerate frontend types: `bun run generate:api`, then add the call in
   `frontend/src/lib/api/endpoints.ts`.
7. Verify: `uv run pytest`, `uv run basedpyright`; on the frontend `bun run check`.

## Repository-specific rules and gotchas

- **Toolchain is fixed:** use `uv` / `ruff` / `basedpyright` (never `pip`/`poetry`/`black`/`flake8`)
  and `bun` (never `npm`/`pnpm`). Biome replaces Prettier+ESLint for the frontend.
- **basedpyright runs in `recommended` mode with no global overrides** — `backend/pyproject.toml`'s
  `[tool.basedpyright]` table is guarded by `tools/check_basedpyright_config.py` (a prek + CI gate).
  Warnings are failures. Do not add `failOnWarnings`, disable a `report*` rule, or add a baseline;
  suppress a single genuinely-untyped call site with `# pyright: ignore[ruleName]` plus a reason.
- **`frontend/src/lib/api/types.gen.ts` is generated** — never hand-edit it; run `bun run generate:api`.
- Backend HTTP: use `msgspec.Struct` (not Pydantic); return the struct and let Litestar encode it;
  get clients from `InstanceGateway` (never instantiate `httpx.AsyncClient()` per request);
  eager-load relationships (lazy loading raises `MissingGreenlet` under async).
- **The SSE bus is UI-only** (`core/sse.py`); never use it for cross-module in-process coordination —
  use an explicit hook seam wired in `app.py` instead.
- Derive rail/usage/stats from `intent_event` history; never introduce a mutable counter for
  spend/usage (breaks restart-safety).
- **Commits to `main` are blocked** by a prek hook and commit messages must be Conventional Commits;
  branch before committing.
- Integration tests exercise `modules/integrations` against in-repo fake upstreams
  (`backend/tests/simulators/{bazarr,lingarr}.py`) via `respx` — extend the simulator when adding a
  new upstream call rather than mocking ad hoc. The `perf` pytest marker needs
  `PEREVODITARR_PERF_DATABASE_URL` and is skipped otherwise.

## References

- `.augment/rules/backend-dev-pro.md` — read before non-trivial backend work; the authoritative
  Litestar / msgspec / SQLAlchemy-async / Alembic idiom reference for this stack.
- `.augment/rules/frontend-dev-pro.md` — read before non-trivial frontend work; Svelte 5 / SvelteKit
  2 / UnoCSS (presetWind4) / shadcn-svelte guidelines.
