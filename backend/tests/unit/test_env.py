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


@pytest.mark.parametrize(
    "bad_line",
    [b"PEREV_TEST_BAD=bad\x00value\n", b"PEREV_TEST\x00BAD=value\n"],
    ids=["nul-in-value", "nul-in-key"],
)
def test_nul_byte_entry_is_skipped_and_neighbors_load(
    bad_line: bytes, tmp_path: Path
) -> None:
    # A NUL byte is valid UTF-8 (0x00), so ``read_text`` succeeds, but
    # ``os.environ`` rejects it (``ValueError: embedded null byte``). The
    # malformed entry must be skipped best-effort — it must not abort the load,
    # so the following valid key still applies. Uses the real ``os.environ``
    # because a plain dict would not reproduce the rejection.
    ok_key = "PEREV_TEST_NUL_OK"
    env_file = tmp_path / "bad.env"
    _ = env_file.write_bytes(bad_line + f"{ok_key}=ok\n".encode())

    _ = os.environ.pop(ok_key, None)
    try:
        load_dotenv_files(paths=[env_file])  # must not raise
        assert os.environ[ok_key] == "ok"
    finally:
        _ = os.environ.pop(ok_key, None)


def test_nul_in_candidate_path_is_skipped_not_raised(tmp_path: Path) -> None:
    # ``Path.resolve`` raises ``ValueError`` (not an ``OSError``) on an embedded
    # NUL. A malformed candidate path must be skipped best-effort so it cannot
    # abort the load; a valid neighbour still contributes. Reachable only via
    # this injected ``paths=`` seam — no real env/filesystem candidate has a NUL.
    ok_key = "PEREV_TEST_PATH_OK"
    good_env = tmp_path / "good.env"
    _ = good_env.write_text(f"{ok_key}=ok\n")

    _ = os.environ.pop(ok_key, None)
    try:
        load_dotenv_files(paths=[Path("bad\x00path.env"), good_env])  # must not raise
        assert os.environ[ok_key] == "ok"
    finally:
        _ = os.environ.pop(ok_key, None)


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
