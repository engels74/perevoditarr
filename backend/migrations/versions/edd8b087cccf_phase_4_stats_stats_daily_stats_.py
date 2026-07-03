"""phase 4 stats: stats_daily, stats_language_daily, lingarr_actuals

Revision ID: edd8b087cccf
Revises: ea1e8e59341a
Create Date: 2026-07-02 23:59:13.652824

The statistics rollup tables (FR-U8): per-(Bazarr instance, UTC day, media type)
outcome counters (`stats_daily`), per-(instance, day, target language) converged
counters for coverage trends (`stats_language_daily`), and the latest reconciled
rolling actuals per Lingarr instance (`lingarr_actuals`, from §6.7 authoritative
statistics). All plain integer/float/date columns — dialect-portable (NFR-2),
re-derived from durable evidence by the rollup job (restart-safe, FR-R4).
"""

from collections.abc import Sequence

import advanced_alchemy.types.datetime
import advanced_alchemy.types.guid
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "edd8b087cccf"
down_revision: str | Sequence[str] | None = "ea1e8e59341a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "lingarr_actuals",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "lingarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=False,
        ),
        sa.Column("sample_files", sa.Integer(), nullable=False),
        sa.Column("lines_per_file", sa.Float(), nullable=False),
        sa.Column("characters_per_file", sa.Float(), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("total_lines", sa.Integer(), nullable=False),
        sa.Column("total_characters", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
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
            ["lingarr_instance_id"],
            ["lingarr_instance.id"],
            name=op.f("fk_lingarr_actuals_lingarr_instance_id_lingarr_instance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lingarr_actuals")),
        sa.UniqueConstraint(
            "lingarr_instance_id", name="uq_lingarr_actuals_lingarr_instance_id"
        ),
    )
    op.create_index(
        op.f("ix_lingarr_actuals_lingarr_instance_id"),
        "lingarr_actuals",
        ["lingarr_instance_id"],
        unique=False,
    )

    op.create_table(
        "stats_daily",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "bazarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("media_type", sa.String(length=8), nullable=False),
        sa.Column("dispatched", sa.Integer(), nullable=False),
        sa.Column("converged", sa.Integer(), nullable=False),
        sa.Column("superseded", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("failed_transient", sa.Integer(), nullable=False),
        sa.Column("failed_environmental", sa.Integer(), nullable=False),
        sa.Column("failed_provider", sa.Integer(), nullable=False),
        sa.Column("failed_poison", sa.Integer(), nullable=False),
        sa.Column("converged_characters", sa.Integer(), nullable=False),
        sa.Column("duration_seconds_total", sa.Integer(), nullable=False),
        sa.Column("duration_samples", sa.Integer(), nullable=False),
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
            name=op.f("fk_stats_daily_bazarr_instance_id_bazarr_instance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stats_daily")),
        sa.UniqueConstraint(
            "bazarr_instance_id",
            "day",
            "media_type",
            name="uq_stats_daily_instance_day_media",
        ),
    )
    op.create_index(
        op.f("ix_stats_daily_bazarr_instance_id"),
        "stats_daily",
        ["bazarr_instance_id"],
        unique=False,
    )
    op.create_index("ix_stats_daily_day", "stats_daily", ["day"], unique=False)
    op.create_index(
        "ix_stats_daily_instance_day",
        "stats_daily",
        ["bazarr_instance_id", "day"],
        unique=False,
    )

    op.create_table(
        "stats_language_daily",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "bazarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("target_language", sa.String(length=8), nullable=False),
        sa.Column("converged", sa.Integer(), nullable=False),
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
            name=op.f("fk_stats_language_daily_bazarr_instance_id_bazarr_instance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stats_language_daily")),
        sa.UniqueConstraint(
            "bazarr_instance_id",
            "day",
            "target_language",
            name="uq_stats_language_daily_instance_day_language",
        ),
    )
    op.create_index(
        op.f("ix_stats_language_daily_bazarr_instance_id"),
        "stats_language_daily",
        ["bazarr_instance_id"],
        unique=False,
    )
    op.create_index(
        "ix_stats_language_daily_instance_day",
        "stats_language_daily",
        ["bazarr_instance_id", "day"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_stats_language_daily_instance_day", table_name="stats_language_daily"
    )
    op.drop_index(
        op.f("ix_stats_language_daily_bazarr_instance_id"),
        table_name="stats_language_daily",
    )
    op.drop_table("stats_language_daily")
    op.drop_index("ix_stats_daily_instance_day", table_name="stats_daily")
    op.drop_index("ix_stats_daily_day", table_name="stats_daily")
    op.drop_index(op.f("ix_stats_daily_bazarr_instance_id"), table_name="stats_daily")
    op.drop_table("stats_daily")
    op.drop_index(
        op.f("ix_lingarr_actuals_lingarr_instance_id"), table_name="lingarr_actuals"
    )
    op.drop_table("lingarr_actuals")
