"""phase 5 webhooks: webhook_source

Revision ID: 41ec01fb47c2
Revises: 1b98c6e82cd9
Create Date: 2026-07-03 12:10:00.000000

Inbound webhook endpoints (P5-T3, FR-X4): per-instance Bazarr/Sonarr discovery
triggers. The secret is stored only as a SHA-256 hash. Dialect-portable
(NFR-2).
"""

from collections.abc import Sequence

import advanced_alchemy.types.datetime
import advanced_alchemy.types.guid
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "41ec01fb47c2"
down_revision: str | Sequence[str] | None = "1b98c6e82cd9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "webhook_source",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column(
            "bazarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
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
            name=op.f("fk_webhook_source_bazarr_instance_id_bazarr_instance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_source")),
        sa.UniqueConstraint("name", name=op.f("uq_webhook_source_name")),
    )
    op.create_index(
        op.f("ix_webhook_source_bazarr_instance_id"),
        "webhook_source",
        ["bazarr_instance_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_source_token_hash"),
        "webhook_source",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_webhook_source_token_hash"), table_name="webhook_source")
    op.drop_index(
        op.f("ix_webhook_source_bazarr_instance_id"), table_name="webhook_source"
    )
    op.drop_table("webhook_source")
