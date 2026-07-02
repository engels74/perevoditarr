"""phase 2 intent ledger: intent and intent_event

Revision ID: d81f5c3a7b26
Revises: b3f1a27d9e40
Create Date: 2026-07-02 14:00:00.000000

The durable intent ledger (PRD §7.1 / FR-R1): natural-key-unique intents plus
the append-only transition audit trail. Index shapes follow the ledger's hot
paths — backlog by priority, in-flight by instance, and the §6.5
scheduling-invariant pair lookups.
"""

from collections.abc import Sequence

import advanced_alchemy.types.datetime
import advanced_alchemy.types.guid
import advanced_alchemy.types.json
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d81f5c3a7b26"
down_revision: str | Sequence[str] | None = "b3f1a27d9e40"
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
        "intent",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "bazarr_instance_id",
            advanced_alchemy.types.guid.GUID(length=16),
            nullable=False,
        ),
        sa.Column("media_type", sa.String(length=8), nullable=False),
        sa.Column("external_media_id", sa.Integer(), nullable=False),
        sa.Column("sonarr_series_id", sa.Integer(), nullable=True),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.Column("display_title", sa.String(length=512), nullable=False),
        sa.Column("source_language", sa.String(length=8), nullable=False),
        sa.Column("target_language", sa.String(length=8), nullable=False),
        sa.Column("forced", sa.Boolean(), nullable=False),
        sa.Column("hi", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("bumped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_trace", _json_column(), nullable=True),
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
            name=op.f("fk_intent_bazarr_instance_id_bazarr_instance"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intent")),
        sa.UniqueConstraint(
            "bazarr_instance_id",
            "media_type",
            "external_media_id",
            "target_language",
            "forced",
            "hi",
            name="uq_intent_identity",
        ),
    )
    op.create_index(
        op.f("ix_intent_bazarr_instance_id"),
        "intent",
        ["bazarr_instance_id"],
        unique=False,
    )
    op.create_index(
        "ix_intent_state_priority", "intent", ["state", "priority"], unique=False
    )
    op.create_index(
        "ix_intent_instance_state",
        "intent",
        ["bazarr_instance_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_intent_series_pair",
        "intent",
        [
            "bazarr_instance_id",
            "sonarr_series_id",
            "source_language",
            "target_language",
        ],
        unique=False,
    )
    op.create_index("ix_intent_created_at", "intent", ["created_at"], unique=False)
    op.create_table(
        "intent_event",
        sa.Column("id", advanced_alchemy.types.guid.GUID(length=16), nullable=False),
        sa.Column(
            "intent_id", advanced_alchemy.types.guid.GUID(length=16), nullable=False
        ),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("from_state", sa.String(length=16), nullable=True),
        sa.Column("to_state", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", _json_column(), nullable=True),
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
            name=op.f("fk_intent_event_intent_id_intent"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_intent_event")),
    )
    op.create_index(
        op.f("ix_intent_event_intent_id"), "intent_event", ["intent_id"], unique=False
    )
    op.create_index(
        "ix_intent_event_intent_created",
        "intent_event",
        ["intent_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_intent_event_intent_created", table_name="intent_event")
    op.drop_index(op.f("ix_intent_event_intent_id"), table_name="intent_event")
    op.drop_table("intent_event")
    op.drop_index("ix_intent_created_at", table_name="intent")
    op.drop_index("ix_intent_series_pair", table_name="intent")
    op.drop_index("ix_intent_instance_state", table_name="intent")
    op.drop_index("ix_intent_state_priority", table_name="intent")
    op.drop_index(op.f("ix_intent_bazarr_instance_id"), table_name="intent")
    op.drop_table("intent")
