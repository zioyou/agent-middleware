"""Add crons table (merge migration)

Revision ID: 20260104150000
Revises: 4c8e2f1a9b73, 20260104120000
Create Date: 2026-01-04 15:00:00.000000

This migration serves as a merge point for two branches:
- 4c8e2f1a9b73 (rate_limit_defaults)
- 20260104120000 (agent_auth_tables)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260104150000"
down_revision: tuple[str, ...] = ("4c8e2f1a9b73", "20260104120000")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create crons table for scheduled agent executions.

    The crons table stores scheduled jobs that run agents at specified intervals
    using cron expressions. Each job can optionally be associated with a specific
    thread for stateful executions.
    """
    op.create_table(
        "crons",
        sa.Column(
            "cron_id",
            sa.Text(),
            server_default=sa.text("uuid_generate_v4()::text"),
            nullable=False,
        ),
        sa.Column("assistant_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("schedule", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("next_run_date", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("end_time", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["assistant_id"],
            ["assistant.assistant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"],
            ["thread.thread_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("cron_id"),
    )

    # Create indexes for common query patterns
    op.create_index("idx_crons_user_id", "crons", ["user_id"])
    op.create_index("idx_crons_assistant_id", "crons", ["assistant_id"])
    op.create_index("idx_crons_thread_id", "crons", ["thread_id"])
    op.create_index("idx_crons_next_run_date", "crons", ["next_run_date"])


def downgrade() -> None:
    """Drop crons table and its indexes."""
    op.drop_index("idx_crons_next_run_date", table_name="crons")
    op.drop_index("idx_crons_thread_id", table_name="crons")
    op.drop_index("idx_crons_assistant_id", table_name="crons")
    op.drop_index("idx_crons_user_id", table_name="crons")
    op.drop_table("crons")
