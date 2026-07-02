"""Typing-gate guard: forbid global basedpyright escape hatches.

The typing contract of this repo: basedpyright runs in ``recommended`` mode
with ``failOnWarnings`` unset — ``recommended`` mode forces it on, making
warnings failures. The only
sanctioned suppression is a single-line ``pyright: ignore[ruleName]`` comment
with a justification, at a genuinely untyped third-party boundary.

This script fails the prek hook and CI when someone — human or AI agent —
tries to reintroduce a global escape hatch:

* extra keys in ``[tool.basedpyright]`` (``failOnWarnings``, ``report* = ...``,
  ``exclude``, ``executionEnvironments``, ...)
* a ``typeCheckingMode`` weaker than ``recommended``
* dropping ``src``/``tests``/``tools`` from the checked paths
* a ``pyrightconfig.json`` (it silently takes precedence over pyproject.toml)
* a basedpyright baseline directory
* file-level pyright configuration pragmas inside checked sources

If this gate blocks you: fix the code. Do not widen the gate.
"""

import re
import sys
import tomllib
from pathlib import Path
from typing import cast

BACKEND_DIR = Path(__file__).resolve().parent.parent

ALLOWED_KEYS = frozenset({"pythonVersion", "typeCheckingMode", "include"})
REQUIRED_MODE = "recommended"
REQUIRED_INCLUDE = frozenset({"src", "tests", "tools"})
FORBIDDEN_PATHS = ("pyrightconfig.json", ".basedpyright")

# A comment starting a line that configures pyright for the whole file
# (e.g. ``basic`` mode or ``reportFoo=false``). Inline, rule-scoped ignore
# comments never start a line, so they are not matched.
FILE_PRAGMA = re.compile(r"^\s*#\s*(?:based)?pyright:\s*(?!ignore\[)")


def load_table(pyproject: Path) -> dict[str, object]:
    with pyproject.open("rb") as fh:
        data: dict[str, object] = tomllib.load(fh)
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return {}
    table = cast("dict[str, object]", tool).get("basedpyright")
    if not isinstance(table, dict):
        return {}
    return cast("dict[str, object]", table)


def included_paths(table: dict[str, object]) -> set[str]:
    include = table.get("include")
    if not isinstance(include, list):
        return set()
    return {item for item in cast("list[object]", include) if isinstance(item, str)}


def check_table(table: dict[str, object]) -> list[str]:
    problems: list[str] = []
    for key in sorted(set(table) - ALLOWED_KEYS):
        problems.append(
            f"[tool.basedpyright] sets {key!r} — global diagnostic overrides are "
            + "forbidden; fix the code or use a justified single-line "
            + "`pyright: ignore[ruleName]` at the offending line instead"
        )
    if table.get("typeCheckingMode") != REQUIRED_MODE:
        problems.append(
            f"[tool.basedpyright] typeCheckingMode must be {REQUIRED_MODE!r}"
        )
    for missing in sorted(REQUIRED_INCLUDE - included_paths(table)):
        problems.append(
            f"[tool.basedpyright] include must keep {missing!r} type-checked"
        )
    return problems


def check_forbidden_paths() -> list[str]:
    return [
        f"{BACKEND_DIR / name} exists — it overrides or baselines away the "
        + "pyproject.toml typing gate; delete it"
        for name in FORBIDDEN_PATHS
        if (BACKEND_DIR / name).exists()
    ]


def check_file_pragmas(roots: frozenset[str]) -> list[str]:
    problems: list[str] = []
    for root in sorted(roots):
        for path in sorted((BACKEND_DIR / root).rglob("*.py")):
            for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if FILE_PRAGMA.match(line):
                    problems.append(
                        f"{path.relative_to(BACKEND_DIR)}:{lineno}: file-level "
                        + "pyright pragma is forbidden; only inline "
                        + "`pyright: ignore[ruleName]` suppressions are allowed"
                    )
    return problems


def main() -> int:
    table = load_table(BACKEND_DIR / "pyproject.toml")
    # scan every configured include dir, not just the required trio, so a
    # pragma can't hide in a newly added include entry
    problems = (
        check_table(table)
        + check_forbidden_paths()
        + check_file_pragmas(REQUIRED_INCLUDE | included_paths(table))
    )
    if problems:
        print("basedpyright config gate FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("basedpyright config gate OK: no global ignores, warnings stay fatal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
