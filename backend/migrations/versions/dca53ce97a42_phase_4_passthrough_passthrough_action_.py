"""phase 4 passthrough: passthrough_action audit

Revision ID: dca53ce97a42
Revises: edd8b087cccf
Create Date: 2026-07-03 00:12:00.000000

Audit trail for user-initiated Lingarr pass-through actions (FR-X3): each
cancel/retry/resume/remove is recorded here so the item timeline (FR-V4) shows
full provenance. Append-only, dialect-portable (NFR-2).
"""

from collections.abc import Sequence

import advanced_alchemy.types.datetime
import advanced_alchemy.types.guid
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dca53ce97a42"
down_revision: str | Sequence[str] | None = "edd8b087cccf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "passthrough_action",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "intent_id", advanced_alchemy.types.guid.GUID(length=16), nullable=False
        ),
        sa.Column("lingarr_request_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
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
            ["intent_id"],
            ["intent.id"],
            name=op.f("fk_passthrough_action_intent_id_intent"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_passthrough_action")),
    )
    op.create_index(
        "ix_passthrough_action_intent_created",
        "passthrough_action",
        ["intent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_passthrough_action_intent_id"),
        "passthrough_action",
        ["intent_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_passthrough_action_intent_id"), table_name="passthrough_action"
    )
    op.drop_index(
        "ix_passthrough_action_intent_created", table_name="passthrough_action"
    )
    op.drop_table("passthrough_action")
