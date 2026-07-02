"""phase 3 rails: rail_state

Revision ID: 70f0a211bdba
Revises: d81f5c3a7b26
Create Date: 2026-07-02 18:57:47.942603

The persisted rail posture (PRD §8.4 / FR-Q3): the operator pause flag, the
per-(Bazarr instance, Lingarr) circuit-breaker state, and per-scope scheduling
windows. Volume-cap and budget usage are intentionally NOT stored — they are
counted from the intent dispatch audit trail on demand (restart-safe, FR-R4).
A row with `bazarr_instance_id IS NULL` is the single global row (service
get-or-create keeps it unique portably, no partial index — NFR-2).
"""

from collections.abc import Sequence

import advanced_alchemy.types.datetime
import advanced_alchemy.types.guid
import advanced_alchemy.types.json
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "70f0a211bdba"
down_revision: str | Sequence[str] | None = "d81f5c3a7b26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json_column() -> sa.types.TypeEngine[object]:
    return (
        sa.JSON()
        .with_variant(postgresql.JSONB(astext_type=sa.Text()), "cockroachdb")
        .with_variant(advanced_alchemy.types.json.ORA_JSONB(), "oracle")
        .with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "rail_state",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "bazarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=True,
        ),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("paused_reason", sa.Text(), nullable=True),
        sa.Column("dispatch_active", sa.Boolean(), nullable=False),
        sa.Column("window_k", sa.Integer(), nullable=True),
        sa.Column("breaker_state", sa.String(length=16), nullable=False),
        sa.Column("breaker_consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("breaker_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("breaker_last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduling_windows", _json_column(), nullable=True),
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
            name=op.f("fk_rail_state_bazarr_instance_id_bazarr_instance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rail_state")),
        sa.UniqueConstraint(
            "bazarr_instance_id", name=op.f("uq_rail_state_bazarr_instance_id")
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("rail_state")
