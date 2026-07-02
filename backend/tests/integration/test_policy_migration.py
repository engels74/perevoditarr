"""Migration seed check (P2-T1): alembic upgrade head ships the four presets
with Observe active — the safe-by-default install posture (PRD §8.3)."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import cast

BACKEND_DIR = Path(__file__).parents[2]


def test_upgrade_head_seeds_presets_with_observe_active(tmp_path: Path) -> None:
    db_path = tmp_path / "migrated.db"
    env = os.environ | {
        "PEREVODITARR_DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
        "PEREVODITARR_SECRET_KEY": "migration-test-secret-0123456789abcdef",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr

    connection = sqlite3.connect(db_path)
    try:
        # sqlite3 rows are untyped; the SELECT fixes the shape.
        rows = cast(
            "list[tuple[str, int, int]]",
            connection.execute(
                "SELECT name, built_in, active FROM preset ORDER BY name"
            ).fetchall(),
        )
    finally:
        connection.close()
    by_name = {name: (bool(built_in), bool(active)) for name, built_in, active in rows}
    assert set(by_name) == {"Observe", "Conservative", "Balanced", "Aggressive"}
    assert all(built_in for built_in, _ in by_name.values())
    assert [name for name, (_, active) in by_name.items() if active] == ["Observe"]
