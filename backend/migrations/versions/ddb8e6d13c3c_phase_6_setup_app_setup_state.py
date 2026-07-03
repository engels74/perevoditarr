"""phase 6 setup: app_setup_state

Revision ID: ddb8e6d13c3c
Revises: 41ec01fb47c2
Create Date: 2026-07-03 17:48:27.789620

Durable first-run completion flag (guided onboarding wizard). Single fixed row
(id = 1); completion is `completed_at IS NOT NULL`. The named CHECK enforces the
singleton on both SQLite and Postgres. The row is never seeded — its absence
means setup is not complete. Dialect-portable (NFR-2): only create_table /
drop_table with a named CheckConstraint.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ddb8e6d13c3c"
down_revision: str | Sequence[str] | None = "41ec01fb47c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "app_setup_state",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_app_setup_state_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_setup_state")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("app_setup_state")
