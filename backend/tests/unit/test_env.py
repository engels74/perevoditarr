import os
from pathlib import Path

import pytest

from perevoditarr.core.env import load_dotenv_files, parse_env_file


def test_parse_basic_comments_export_and_quotes() -> None:
    parsed = parse_env_file(
        "\n".join(
            [
                "# a comment",
                "",
                "FOO=bar",
                "export BAZ=qux",
                'QUOTED="hello world"',
                "SINGLE='it works'",
                "INLINE=value # trailing",
                "URL=postgresql+asyncpg://u:p@h/db?x=1",
                "  SPACED = spaced value ",
                "NOEQ",
                "=noval",
            ]
        )
    )
    assert parsed == {
        "FOO": "bar",
        "BAZ": "qux",
        "QUOTED": "hello world",
        "SINGLE": "it works",
        "INLINE": "value",
        "URL": "postgresql+asyncpg://u:p@h/db?x=1",
        "SPACED": "spaced value",
    }


def test_quoted_value_preserves_hash_and_inner_spaces() -> None:
    parsed = parse_env_file('SECRET="a b # c"')
    assert parsed["SECRET"] == "a b # c"


def test_quoted_value_with_trailing_inline_comment() -> None:
    parsed = parse_env_file(
        "\n".join(
            [
                'DQ="value" # a comment',
                "SQ='works' # another",
                'EMPTY=""',
            ]
        )
    )
    assert parsed == {"DQ": "value", "SQ": "works", "EMPTY": ""}


def test_load_dotenv_no_override_and_backend_beats_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_env = tmp_path / "root.env"
    backend_env = tmp_path / "backend.env"
    _ = root_env.write_text("SHARED=root\nONLY_ROOT=r\nREAL=fromfile\n")
    _ = backend_env.write_text("SHARED=backend\nONLY_BACKEND=b\n")

    fake_environ: dict[str, str] = {"REAL": "fromenv"}
    monkeypatch.setattr(os, "environ", fake_environ)

    # backend before root: more-specific file wins, real environment wins overall.
    load_dotenv_files(paths=[backend_env, root_env])

    assert fake_environ["REAL"] == "fromenv"
    assert fake_environ["SHARED"] == "backend"
    assert fake_environ["ONLY_ROOT"] == "r"
    assert fake_environ["ONLY_BACKEND"] == "b"


def test_missing_files_are_skipped_silently(tmp_path: Path) -> None:
    load_dotenv_files(paths=[tmp_path / "does-not-exist.env"])  # must not raise


def test_env_file_override_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom.env"
    _ = override.write_text("PEREV_TEST_OVERRIDE=yes\n")

    # No real backend/.env or repo-root/.env exists in the tree, so only the
    # explicit override contributes here.
    fake_environ: dict[str, str] = {"PEREVODITARR_ENV_FILE": str(override)}
    monkeypatch.setattr(os, "environ", fake_environ)

    load_dotenv_files()

    assert fake_environ["PEREV_TEST_OVERRIDE"] == "yes"
