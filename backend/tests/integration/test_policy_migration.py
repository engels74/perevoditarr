"""Migration seed check (P2-T1): alembic upgrade head ships the four presets
with Observe active — the safe-by-default install posture (PRD §8.3)."""

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from typing import cast

import msgspec

BACKEND_DIR = Path(__file__).parents[2]

type PresetPayload = tuple[str, str, bool, bool, dict[str, object], dict[str, object]]

EXPECTED_PRESETS: dict[str, PresetPayload] = {
    "Observe": (
        "019739a0-0000-7000-8000-000000000001",
        "Dry-run only. Discovers, plans, and reports — dispatches nothing. "
        + "The default posture on install.",
        True,
        True,
        {"dry_run": True},
        {},
    ),
    "Conservative": (
        "019739a0-0000-7000-8000-000000000002",
        "K=1, low daily cap, long grace periods, tight breaker — for cautious "
        + "starts and paid providers.",
        True,
        False,
        {
            "dry_run": False,
            "grace_hours_episodes": 336,
            "grace_hours_movies": 720,
        },
        {
            "dispatch_window_k": 1,
            "daily_cap": 50,
            "breaker_failure_threshold": 3,
            "breaker_probe_minutes": 30,
        },
    ),
    "Balanced": (
        "019739a0-0000-7000-8000-000000000003",
        "Moderate caps and window, budget ceiling on — sane defaults for paid "
        + "providers.",
        True,
        False,
        {
            "dry_run": False,
            "grace_hours_episodes": 168,
            "grace_hours_movies": 336,
        },
        {
            "dispatch_window_k": 2,
            "daily_cap": 200,
            "budget_daily_characters": 2_000_000,
            "breaker_failure_threshold": 5,
            "breaker_probe_minutes": 15,
        },
    ),
    "Aggressive": (
        "019739a0-0000-7000-8000-000000000004",
        "Higher K and caps, short grace — for free/local providers.",
        True,
        False,
        {
            "dry_run": False,
            "grace_hours_episodes": 48,
            "grace_hours_movies": 72,
        },
        {
            "dispatch_window_k": 3,
            "daily_cap": 1000,
            "breaker_failure_threshold": 8,
            "breaker_probe_minutes": 10,
        },
    ),
}


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
            "list[tuple[bytes, str, str, int, int, str, str]]",
            connection.execute(
                'SELECT id, name, description, built_in, active, "values", rails '
                + "FROM preset ORDER BY name"
            ).fetchall(),
        )
    finally:
        connection.close()
    by_name: dict[str, PresetPayload] = {
        name: (
            str(uuid.UUID(bytes=row_id)),
            description,
            bool(built_in),
            bool(active),
            msgspec.json.decode(values.encode(), type=dict[str, object]),
            msgspec.json.decode(rails.encode(), type=dict[str, object]),
        )
        for row_id, name, description, built_in, active, values, rails in rows
    }
    assert by_name == EXPECTED_PRESETS
