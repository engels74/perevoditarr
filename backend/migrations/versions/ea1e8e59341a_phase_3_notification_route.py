"""phase 3 notifications: notification_route

Revision ID: ea1e8e59341a
Revises: 70f0a211bdba
Create Date: 2026-07-02 19:46:01.765200

Apprise notification routes (PRD FR-X1): the per-event routing matrix. The
target URL carries credentials, so it is stored Fernet-encrypted at rest
(FR-A5) and never returned in plaintext.
"""

from collections.abc import Sequence

import advanced_alchemy.types.datetime
import advanced_alchemy.types.guid
import advanced_alchemy.types.json
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ea1e8e59341a"
down_revision: str | Sequence[str] | None = "70f0a211bdba"
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
        "notification_route",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("url_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("events", _json_column(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_route")),
        sa.UniqueConstraint("name", name=op.f("uq_notification_route_name")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("notification_route")
