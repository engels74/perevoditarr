"""Regression tests for tools/check_basedpyright_config.py (the typing gate).

The gate is load-bearing: it is what stops a future contributor — human or
AI agent — from quietly re-adding global basedpyright ignores. Each test runs
the gate script against a synthetic project tree, proving every escape hatch
still fails and that the one sanctioned suppression form still passes.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GATE_SOURCE = (
    Path(__file__).resolve().parent.parent.parent
    / "tools"
    / "check_basedpyright_config.py"
)

STRICT_TABLE = """\
[tool.basedpyright]
pythonVersion = "3.14"
typeCheckingMode = "recommended"
include = ["src", "tests", "tools"]
"""


def run_gate(tree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(tree / "tools" / "check_basedpyright_config.py")],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    for sub in ("src", "tests", "tools"):
        (tmp_path / sub).mkdir()
    _ = shutil.copy(GATE_SOURCE, tmp_path / "tools" / "check_basedpyright_config.py")
    _ = (tmp_path / "pyproject.toml").write_text(STRICT_TABLE, encoding="utf-8")
    return tmp_path


def test_strict_config_passes(tree: Path) -> None:
    result = run_gate(tree)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "override",
    [
        "failOnWarnings = false",
        "reportMissingTypeStubs = false",
        'reportAny = "hint"',
        'exclude = ["src/hard_module"]',
        "[tool.basedpyright.executionEnvironments]",
    ],
)
def test_global_overrides_fail(tree: Path, override: str) -> None:
    _ = (tree / "pyproject.toml").write_text(
        STRICT_TABLE + override + "\n", encoding="utf-8"
    )
    result = run_gate(tree)
    assert result.returncode == 1
    assert "global diagnostic overrides are forbidden" in result.stderr


def test_weakened_mode_fails(tree: Path) -> None:
    _ = (tree / "pyproject.toml").write_text(
        STRICT_TABLE.replace("recommended", "standard"), encoding="utf-8"
    )
    result = run_gate(tree)
    assert result.returncode == 1
    assert "typeCheckingMode" in result.stderr


def test_dropped_include_fails(tree: Path) -> None:
    _ = (tree / "pyproject.toml").write_text(
        STRICT_TABLE.replace('["src", "tests", "tools"]', '["src"]'),
        encoding="utf-8",
    )
    result = run_gate(tree)
    assert result.returncode == 1
    assert "'tests'" in result.stderr
    assert "'tools'" in result.stderr


def test_pyrightconfig_json_fails(tree: Path) -> None:
    _ = (tree / "pyrightconfig.json").write_text("{}", encoding="utf-8")
    result = run_gate(tree)
    assert result.returncode == 1
    assert "pyrightconfig.json" in result.stderr


def test_baseline_dir_fails(tree: Path) -> None:
    (tree / ".basedpyright").mkdir()
    result = run_gate(tree)
    assert result.returncode == 1
    assert ".basedpyright" in result.stderr


@pytest.mark.parametrize(
    "pragma",
    ["# pyright: reportAny=false", "# pyright: basic", "# basedpyright: standard"],
)
def test_file_level_pragma_fails(tree: Path, pragma: str) -> None:
    _ = (tree / "src" / "sneaky.py").write_text(pragma + "\nx = 1\n", encoding="utf-8")
    result = run_gate(tree)
    assert result.returncode == 1
    assert "file-level" in result.stderr


def test_pragma_scan_covers_extra_include_dirs(tree: Path) -> None:
    (tree / "extra").mkdir()
    _ = (tree / "pyproject.toml").write_text(
        STRICT_TABLE.replace(
            'include = ["src", "tests", "tools"]',
            'include = ["src", "tests", "tools", "extra"]',
        ),
        encoding="utf-8",
    )
    _ = (tree / "extra" / "sneaky.py").write_text(
        "# pyright: basic\nx = 1\n", encoding="utf-8"
    )
    result = run_gate(tree)
    assert result.returncode == 1
    assert "file-level" in result.stderr


def test_inline_rule_scoped_ignore_allowed(tree: Path) -> None:
    _ = (tree / "src" / "honest.py").write_text(
        'import os\n\ny = os.getenv("X")  # pyright: ignore[reportAny]  # boundary\n',
        encoding="utf-8",
    )
    result = run_gate(tree)
    assert result.returncode == 0, result.stderr
