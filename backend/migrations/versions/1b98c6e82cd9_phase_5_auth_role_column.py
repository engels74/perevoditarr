"""phase 5 auth: role column

Revision ID: 1b98c6e82cd9
Revises: a8a87bee47ea
Create Date: 2026-07-03 12:01:35.968311

Replaces the boolean `is_admin` on user_account with a `role` column
(admin | viewer, FR-A6 / ADR-0008). Existing admins backfill to 'admin'.
Dialect-portable (NFR-2): batch_alter_table keeps SQLite happy, and the
CASE/boolean expressions render on both engines.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b98c6e82cd9"
down_revision: str | Sequence[str] | None = "a8a87bee47ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("user_account") as batch_op:
        batch_op.add_column(
            sa.Column(
                "role", sa.String(length=16), nullable=False, server_default="admin"
            )
        )
    op.execute(
        "UPDATE user_account SET role = "
        "CASE WHEN is_admin THEN 'admin' ELSE 'viewer' END"
    )
    with op.batch_alter_table("user_account") as batch_op:
        batch_op.drop_column("is_admin")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("user_account") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    op.execute("UPDATE user_account SET is_admin = (role = 'admin')")
    with op.batch_alter_table("user_account") as batch_op:
        batch_op.drop_column("role")
