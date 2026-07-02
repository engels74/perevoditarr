# syntax=docker/dockerfile:1
# Multi-stage, multi-arch (amd64/arm64) image: Bun builds the static SPA, uv builds
# the Python backend, and Litestar serves /api/v1, /schema, SSE, and the SPA with an
# index.html fallback (ADR-0004). Build context is the repository root.

# ---- Stage 1: SPA build (Bun) --------------------------------------------------
FROM oven/bun:1.3 AS spa-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/bun.lock frontend/bunfig.toml ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
RUN bun --bun vite build

# ---- Stage 2: backend build (uv) -----------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim AS backend-build
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app/backend
# dependency layer first, project second — keeps rebuilds cheap
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Stage 3: runtime -----------------------------------------------------------
FROM python:3.14-slim-trixie AS runtime
LABEL org.opencontainers.image.title="Perevoditarr" \
      org.opencontainers.image.description="Orchestration and observability between Bazarr and Lingarr" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.source="https://github.com/engels74/perevoditarr"

RUN useradd --system --create-home --uid 1000 perevoditarr
WORKDIR /app/backend

COPY --from=backend-build --chown=perevoditarr:perevoditarr /app/backend /app/backend
COPY --from=spa-build --chown=perevoditarr:perevoditarr /build/frontend/build /app/spa

ENV PATH="/app/backend/.venv/bin:$PATH" \
    LITESTAR_APP=perevoditarr.app:app \
    PEREVODITARR_SPA_DIR=/app/spa

USER perevoditarr
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]

# Schema is Alembic's job (never create_all): migrate, then serve.
CMD ["sh", "-c", "alembic upgrade head && exec litestar run --host 0.0.0.0 --port 8000"]
