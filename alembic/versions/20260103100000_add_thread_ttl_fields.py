"""Add TTL fields to thread table for threads.update SDK support

Revision ID: b3f2c8d4e5a6
Revises: aee821a02fc8
Create Date: 2026-01-03 10:00:00.000000

This migration adds Time-to-Live (TTL) support for threads:
- ttl_seconds: Duration in seconds before thread expires
- ttl_strategy: Expiration strategy ('delete' or 'archive')
- expires_at: Calculated expiration timestamp

A partial index on expires_at optimizes the cleanup query for expired threads.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "b3f2c8d4e5a6"
down_revision = "aee821a02fc8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add TTL fields to thread table
    op.add_column(
        "thread",
        sa.Column("ttl_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "thread",
        sa.Column("ttl_strategy", sa.Text(), nullable=True),
    )
    op.add_column(
        "thread",
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # Create partial index for efficient expired thread queries
    # Only indexes rows where expires_at is not null
    op.create_index(
        "idx_thread_expires_at",
        "thread",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    # Drop index first
    op.drop_index("idx_thread_expires_at", table_name="thread")

    # Drop columns
    op.drop_column("thread", "expires_at")
    op.drop_column("thread", "ttl_strategy")
    op.drop_column("thread", "ttl_seconds")
