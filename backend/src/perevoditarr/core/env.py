"""Optional ``.env`` file loading for local / self-hosted runs.

The typed settings layer (``core.settings``) intentionally reads only
``os.environ``. To let a single ``.env`` at the repository root (or a
``backend/.env`` next to the package) work for ``litestar run``, the admin CLI,
and Alembic without a manual ``export``, ``load_dotenv_files`` parses those
files and fills ``os.environ`` — **never overriding** a variable already set in
the real environment.

Precedence (highest first):

1. the real process environment (already present in ``os.environ``);
2. ``$PEREVODITARR_ENV_FILE`` (explicit override, if set);
3. ``backend/.env`` (backend-local override);
4. ``<repo root>/.env`` (the shared file both services read).

This is a convenience for source / Compose deployments; a production
orchestrator may keep injecting plain environment variables and ship no
``.env`` at all — every candidate that is absent or unreadable is simply
skipped. No third-party dependency is used: the ``KEY=value`` grammar here is
small enough to parse directly, and it keeps the settings layer's fail-fast,
minimal-surface contract intact.
"""

import os
from collections.abc import Iterable
from pathlib import Path

# Escape hatch: point at an explicit env file regardless of the layout below.
ENV_FILE_OVERRIDE = "PEREVODITARR_ENV_FILE"

# ``core/env.py`` -> ``perevoditarr`` -> ``src`` -> ``backend`` -> ``<repo root>``.
_BACKEND_DIR_DEPTH = 3
_REPO_ROOT_DEPTH = 4


def _nth_parent(path: Path, depth: int) -> Path | None:
    parents = path.parents
    return parents[depth] if depth < len(parents) else None


def _candidate_paths() -> list[Path]:
    """Env files to consider, most-specific first (see module docstring)."""
    here = Path(__file__).resolve()
    candidates: list[Path] = []
    override = os.environ.get(ENV_FILE_OVERRIDE)
    if override:
        candidates.append(Path(override))
    backend_dir = _nth_parent(here, _BACKEND_DIR_DEPTH)
    if backend_dir is not None:
        candidates.append(backend_dir / ".env")
    repo_root = _nth_parent(here, _REPO_ROOT_DEPTH)
    if repo_root is not None:
        candidates.append(repo_root / ".env")
    return candidates


def _strip_inline_comment(value: str) -> str:
    # Only for unquoted values: a `` #`` sequence starts a trailing comment.
    marker = value.find(" #")
    return value[:marker].rstrip() if marker != -1 else value


def _unquote(value: str) -> str:
    # Quoted value: return the content between the opening quote and its match,
    # dropping anything after the closing quote (e.g. a trailing inline comment
    # like `"value" # note`). Inner `#` and spaces are preserved.
    if value and value[0] in {'"', "'"}:
        end = value.find(value[0], 1)
        if end != -1:
            return value[1:end]
    # Unquoted (or an unterminated quote): a ` #` starts a trailing comment.
    return _strip_inline_comment(value)


def parse_env_file(text: str) -> dict[str, str]:
    """Parse ``KEY=value`` lines into a mapping.

    Supports blank lines, ``#`` comment lines, an optional ``export`` prefix,
    single/double-quoted values (quotes stripped, inner content preserved), and
    trailing inline comments on unquoted values. The first ``=`` splits key from
    value, so values may themselves contain ``=`` (e.g. DB URLs, secrets).
    """
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        values[key] = _unquote(value.strip())
    return values


def load_dotenv_files(paths: Iterable[Path] | None = None) -> None:
    """Fill ``os.environ`` from the candidate ``.env`` files, without override.

    Idempotent and best-effort: a missing, unreadable, or non-UTF-8 file is
    skipped silently. ``os.environ.setdefault`` guarantees the real environment
    (and any earlier, more-specific file) always wins. ``paths`` defaults to
    :func:`_candidate_paths`; it is an injectable seam for tests.
    """
    resolved_candidates = _candidate_paths() if paths is None else list(paths)
    seen: set[Path] = set()
    for path in resolved_candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            text = resolved.read_text(encoding="utf-8")
        except OSError, UnicodeDecodeError:
            continue
        for key, value in parse_env_file(text).items():
            _ = os.environ.setdefault(key, value)
