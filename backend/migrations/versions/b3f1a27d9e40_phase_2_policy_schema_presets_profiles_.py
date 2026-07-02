"""phase 2 policy schema: presets, profiles, assignments, exclusions, overrides

Revision ID: b3f1a27d9e40
Revises: c4ede387c88f
Create Date: 2026-07-02 12:00:00.000000

Seeds the four shipped presets (PRD §8.3) with **Observe** active on install:
safe-by-default means a fresh install discovers and plans but dispatches
nothing until the operator explicitly activates a dispatching posture.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import advanced_alchemy.types.datetime
import advanced_alchemy.types.guid
import advanced_alchemy.types.json
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b3f1a27d9e40"
down_revision: str | Sequence[str] | None = "c4ede387c88f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_column() -> sa.types.TypeEngine[object]:
    return (
        sa.JSON()
        .with_variant(postgresql.JSONB(astext_type=sa.Text()), "cockroachdb")
        .with_variant(advanced_alchemy.types.json.ORA_JSONB(), "oracle")
        .with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    )


# Stable seed identities so re-imports and docs can reference them.
OBSERVE_ID = uuid.UUID("019739a0-0000-7000-8000-000000000001")
CONSERVATIVE_ID = uuid.UUID("019739a0-0000-7000-8000-000000000002")
BALANCED_ID = uuid.UUID("019739a0-0000-7000-8000-000000000003")
AGGRESSIVE_ID = uuid.UUID("019739a0-0000-7000-8000-000000000004")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "preset",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("built_in", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("values", _json_column(), nullable=True),
        sa.Column("rails", _json_column(), nullable=True),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_preset")),
        sa.UniqueConstraint("name", name=op.f("uq_preset_name")),
    )
    op.create_index(op.f("ix_preset_active"), "preset", ["active"], unique=False)
    op.create_table(
        "translation_profile",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("values", _json_column(), nullable=True),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_translation_profile")),
        sa.UniqueConstraint("name", name=op.f("uq_translation_profile_name")),
    )
    op.create_table(
        "profile_assignment",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "profile_id", advanced_alchemy.types.guid.GUID(length=16), nullable=False
        ),
        sa.Column(
            "bazarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_key", sa.String(length=128), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bazarr_instance_id"],
            ["bazarr_instance.id"],
            name=op.f("fk_profile_assignment_bazarr_instance_id_bazarr_instance"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["translation_profile.id"],
            name=op.f("fk_profile_assignment_profile_id_translation_profile"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_profile_assignment")),
        sa.UniqueConstraint(
            "bazarr_instance_id",
            "scope_type",
            "scope_key",
            name=op.f("uq_profile_assignment_bazarr_instance_id"),
        ),
    )
    op.create_index(
        op.f("ix_profile_assignment_profile_id"),
        "profile_assignment",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        "ix_profile_assignment_instance",
        "profile_assignment",
        ["bazarr_instance_id"],
        unique=False,
    )
    op.create_table(
        "exclusion",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "bazarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("rule_key", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bazarr_instance_id"],
            ["bazarr_instance.id"],
            name=op.f("fk_exclusion_bazarr_instance_id_bazarr_instance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exclusion")),
        sa.UniqueConstraint(
            "bazarr_instance_id",
            "kind",
            "rule_key",
            name=op.f("uq_exclusion_bazarr_instance_id"),
        ),
    )
    op.create_index(
        "ix_exclusion_instance_kind",
        "exclusion",
        ["bazarr_instance_id", "kind"],
        unique=False,
    )
    op.create_table(
        "override",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "bazarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=False,
        ),
        sa.Column("media_type", sa.String(length=8), nullable=False),
        sa.Column("media_key", sa.String(length=32), nullable=False),
        sa.Column("values", _json_column(), nullable=True),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            advanced_alchemy.types.datetime.DateTimeUTC(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bazarr_instance_id"],
            ["bazarr_instance.id"],
            name=op.f("fk_override_bazarr_instance_id_bazarr_instance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_override")),
        sa.UniqueConstraint(
            "bazarr_instance_id",
            "media_type",
            "media_key",
            name=op.f("uq_override_bazarr_instance_id"),
        ),
    )
    op.create_index(
        "ix_override_instance", "override", ["bazarr_instance_id"], unique=False
    )

    _seed_presets()


def _seed_presets() -> None:
    preset = sa.table(
        "preset",
        sa.column("id", advanced_alchemy.types.guid.GUID(length=16)),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("built_in", sa.Boolean()),
        sa.column("active", sa.Boolean()),
        sa.column("values", _json_column()),
        sa.column("rails", _json_column()),
        sa.column(
            "created_at", advanced_alchemy.types.datetime.DateTimeUTC(timezone=True)
        ),
        sa.column(
            "updated_at", advanced_alchemy.types.datetime.DateTimeUTC(timezone=True)
        ),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        preset,
        [
            {
                "id": OBSERVE_ID,
                "name": "Observe",
                "description": (
                    "Dry-run only. Discovers, plans, and reports — dispatches "
                    "nothing. The default posture on install."
                ),
                "built_in": True,
                "active": True,
                "values": {"dry_run": True},
                "rails": {},
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": CONSERVATIVE_ID,
                "name": "Conservative",
                "description": (
                    "K=1, low daily cap, long grace periods, tight breaker — "
                    "for cautious starts and paid providers."
                ),
                "built_in": True,
                "active": False,
                "values": {
                    "dry_run": False,
                    "grace_hours_episodes": 336,
                    "grace_hours_movies": 720,
                },
                "rails": {
                    "dispatch_window_k": 1,
                    "daily_cap": 50,
                    "breaker_failure_threshold": 3,
                    "breaker_probe_minutes": 30,
                },
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": BALANCED_ID,
                "name": "Balanced",
                "description": (
                    "Moderate caps and window, budget ceiling on — sane "
                    "defaults for paid providers."
                ),
                "built_in": True,
                "active": False,
                "values": {
                    "dry_run": False,
                    "grace_hours_episodes": 168,
                    "grace_hours_movies": 336,
                },
                "rails": {
                    "dispatch_window_k": 2,
                    "daily_cap": 200,
                    "budget_daily_characters": 2_000_000,
                    "breaker_failure_threshold": 5,
                    "breaker_probe_minutes": 15,
                },
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": AGGRESSIVE_ID,
                "name": "Aggressive",
                "description": (
                    "Higher K and caps, short grace — for free/local providers."
                ),
                "built_in": True,
                "active": False,
                "values": {
                    "dry_run": False,
                    "grace_hours_episodes": 48,
                    "grace_hours_movies": 72,
                },
                "rails": {
                    "dispatch_window_k": 3,
                    "daily_cap": 1000,
                    "breaker_failure_threshold": 8,
                    "breaker_probe_minutes": 10,
                },
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_override_instance", table_name="override")
    op.drop_table("override")
    op.drop_index("ix_exclusion_instance_kind", table_name="exclusion")
    op.drop_table("exclusion")
    op.drop_index("ix_profile_assignment_instance", table_name="profile_assignment")
    op.drop_index(
        op.f("ix_profile_assignment_profile_id"), table_name="profile_assignment"
    )
    op.drop_table("profile_assignment")
    op.drop_table("translation_profile")
    op.drop_index(op.f("ix_preset_active"), table_name="preset")
    op.drop_table("preset")
