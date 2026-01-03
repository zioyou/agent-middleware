"""Add indexes for status_code and is_streaming to audit_logs

Revision ID: 8a4f5e7c9d12
Revises: 0e3e9236b1fc
Create Date: 2026-01-03 21:30:00.000000

These indexes optimize common query patterns:
- status_code index: Filter by HTTP response status (e.g., find all 5xx errors)
- is_streaming index: Filter SSE/streaming responses for monitoring
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "8a4f5e7c9d12"
down_revision = "0e3e9236b1fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add indexes for status_code and is_streaming columns."""
    # Index for filtering by HTTP status code (error analysis)
    op.create_index(
        "idx_audit_logs_status_code",
        "audit_logs",
        ["status_code"],
        unique=False,
    )

    # Partial index for streaming responses (most are non-streaming)
    # Only indexes rows where is_streaming = true for efficiency
    op.create_index(
        "idx_audit_logs_streaming",
        "audit_logs",
        ["is_streaming"],
        unique=False,
        postgresql_where=sa.text("is_streaming = true"),
    )


def downgrade() -> None:
    """Remove status_code and is_streaming indexes."""
    op.drop_index("idx_audit_logs_streaming", table_name="audit_logs")
    op.drop_index("idx_audit_logs_status_code", table_name="audit_logs")
