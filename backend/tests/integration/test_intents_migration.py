"""Migration check (P2-T2): alembic upgrade head creates the intent ledger
tables with the natural-key unique constraint — and the revision chain has a
single head (upgrade fails otherwise)."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import cast

BACKEND_DIR = Path(__file__).parents[2]


def test_upgrade_head_creates_intent_ledger(tmp_path: Path) -> None:
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
        table_query = "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('intent', 'intent_event') ORDER BY name"
        tables = cast("list[tuple[str]]", connection.execute(table_query).fetchall())
        index_query = (
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='intent'"
        )
        indexes = cast("list[tuple[str]]", connection.execute(index_query).fetchall())
        ddl_query = "SELECT sql FROM sqlite_master WHERE type='table' AND name='intent'"
        (intent_ddl,) = cast("tuple[str]", connection.execute(ddl_query).fetchone())
    finally:
        connection.close()
    assert [name for (name,) in tables] == ["intent", "intent_event"]
    # SQLite realizes table-level UNIQUE constraints as unnamed autoindexes;
    # the constraint name survives only in the table DDL.
    assert "uq_intent_identity" in intent_ddl
    index_names = {name for (name,) in indexes}
    assert "ix_intent_series_pair" in index_names
    assert "ix_intent_state_priority" in index_names
