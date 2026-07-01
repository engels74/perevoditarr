# Contributing to Perevoditarr

Perevoditarr is a self-hosted orchestration and observability application that sits
between Bazarr and Lingarr. Before writing any code, read:

- **`docs/perevoditarr-prd.md`** — the product requirements document. §6 (integration
  reality) and §7 (architecture principles) are **normative**; violations of the
  project invariants they define are defects, not style issues.
- **`docs/perevoditarr-implementation-plan.md`** — the phased implementation plan.
  Standing conventions (§0) apply to every task and every PR.
- **`.augment/rules/backend-dev-pro.md`** — binding coding guidelines for all backend
  work (Python 3.14 / Litestar 2.x / Granian / msgspec / SQLAlchemy 2.0 async /
  Advanced Alchemy / Alembic / structlog / httpx; uv + ruff + basedpyright).
- **`.augment/rules/frontend-dev-pro.md`** — binding coding guidelines for all frontend
  work (Bun / Svelte 5 runes / SvelteKit 2 / UnoCSS presetWind4 / shadcn-svelte).
- **`docs/adr/`** — architecture decision records. ADRs capture the load-bearing
  decisions; do not contradict an accepted ADR without superseding it.

Where the PRD and the rules files conflict on implementation idiom, the rules files
win; where they conflict on product behavior, the PRD wins.

## Toolchain

| Area | Tool | Never |
|---|---|---|
| Backend packages | [`uv`](https://docs.astral.sh/uv/) (`uv add`, `uv sync`, `uv run`) | pip, poetry, pdm |
| Backend lint/format | `ruff format` + `ruff check --fix` | black, isort, flake8 |
| Backend types | `basedpyright` (`recommended` mode) | mypy, plain pyright |
| Frontend packages | [`bun`](https://bun.com/) (`bun install`, `bun add`) | npm, pnpm, yarn |
| Frontend tests | `bun test` (bun:test) | jest, vitest |
| Git hooks | [`prek`](https://prek.j178.dev/) | pre-commit (Python) |

## One-time setup

```bash
# Backend
cd backend && uv sync

# Frontend
cd frontend && bun install

# Git hooks — prek (Rust-native pre-commit runner)
uv tool install prek          # or: curl --proto '=https' --tlsv1.2 -LsSf https://github.com/j178/prek/releases/latest/download/prek-installer.sh | sh
prek install --hook-type pre-commit --hook-type commit-msg
```

The `commit-msg` stage is required — it enforces
[Conventional Commits](https://www.conventionalcommits.org/) on every commit message.

## Quality gates

Hooks (fast: format / lint / type-check) run on every commit via `prek`. Fix findings —
bypassing with `--no-verify` is a review blocker. Tests and builds run in CI.

```bash
# Backend
cd backend
uv run ruff format
uv run ruff check --fix
uv run basedpyright
uv run pytest

# Frontend
cd frontend
bun run check     # svelte-check
bun run lint      # eslint + prettier --check
bun test
bun --bun vite build

# All hooks against the whole tree
prek run --all-files
```

## Repository layout

```
perevoditarr/
├─ .augment/rules/      # binding coding guidelines (backend + frontend)
├─ backend/             # Python 3.14 / Litestar — src/perevoditarr/{app.py,cli.py,core/,modules/}
├─ frontend/            # Bun / Svelte 5 / SvelteKit 2 static SPA
├─ docker/              # Dockerfile + compose examples
├─ docs/                # PRD, implementation plan, ADRs (docs/adr/)
└─ .github/workflows/   # CI
```

Each bounded area (auth, instances, mirror, policy, intents, dispatch, rails, doctor,
telemetry, notifications, stats, integrations) is its own module with its own
controllers|routes, services, repositories, and schemas|types. Cross-feature access
goes through public module interfaces only.

## Commits and branches

- Conventional Commits, enforced by the `commit-msg` hook.
- Never commit directly to `main` (enforced by the `no-commit-to-branch` hook);
  branch and open a PR.
- Commit `uv.lock` and `bun.lock`; CI installs with `uv sync --frozen` /
  `bun install --frozen-lockfile`.

## License

Perevoditarr is licensed under AGPL-3.0. Contributions are accepted under the same
license.
