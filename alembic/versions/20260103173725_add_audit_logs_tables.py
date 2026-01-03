"""Add audit logging tables with PostgreSQL partitioning

Revision ID: 0e3e9236b1fc
Revises: 20260103131252
Create Date: 2026-01-03 17:37:25.391992

This migration adds:
1. audit_logs_outbox - Outbox table for reliable audit log capture
2. audit_logs - Partitioned table for efficient audit log storage

Architecture Notes:
- Outbox pattern: Middleware INSERTs synchronously to outbox, background mover
  transfers to partitioned table
- Partitioning: RANGE by timestamp (monthly partitions)
- Initial partitions: Created for current month + 3 months ahead

Codex Architecture Review Incorporated:
- Outbox pattern for crash-safe logging
- Composite PK (id, timestamp) required for partitioning
- Schema-aware masking with size limits (10KB)
- org_id scoping for multi-tenant isolation
"""

import re
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "0e3e9236b1fc"
down_revision = "20260103131252"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create audit logging tables and initial partitions."""

    # 1. Create audit_logs partitioned table
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("http_method", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "request_body",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "response_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column(
            "is_streaming",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", "timestamp"),
        postgresql_partition_by="RANGE (timestamp)",
    )

    # Create indexes on audit_logs
    op.create_index(
        "idx_audit_logs_action", "audit_logs", ["action"], unique=False
    )
    op.create_index(
        "idx_audit_logs_org_timestamp",
        "audit_logs",
        ["org_id", "timestamp"],
        unique=False,
    )
    op.create_index(
        "idx_audit_logs_resource",
        "audit_logs",
        ["resource_type", "resource_id"],
        unique=False,
    )
    op.create_index(
        "idx_audit_logs_user_timestamp",
        "audit_logs",
        ["user_id", "timestamp"],
        unique=False,
    )

    # 2. Create initial partitions (current month + 3 months ahead)
    now = datetime.now(UTC)

    def add_months(dt: datetime, months: int) -> datetime:
        """Add months to a datetime, handling month overflow."""
        month = dt.month + months - 1
        year = dt.year + month // 12
        month = month % 12 + 1
        return dt.replace(year=year, month=month)

    for i in range(4):  # Current month + 3 future months
        month_start = add_months(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), i)
        month_end = add_months(month_start, 1)
        partition_name = f"audit_logs_y{month_start.year}m{month_start.month:02d}"

        # Security: Validate partition name format to prevent SQL injection patterns
        if not re.match(r"^audit_logs_y\d{4}m\d{2}$", partition_name):
            raise ValueError(f"Invalid partition name format: {partition_name}")

        # Create partition with raw SQL (Alembic doesn't have native partition support)
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {partition_name}
            PARTITION OF audit_logs
            FOR VALUES FROM ('{month_start.strftime('%Y-%m-%d')}')
            TO ('{month_end.strftime('%Y-%m-%d')}')
            """
        )

    # 3. Create audit_logs_outbox table
    op.create_table(
        "audit_logs_outbox",
        sa.Column(
            "id",
            sa.Text(),
            server_default=sa.text("uuid_generate_v4()::text"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "processed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create partial index on audit_logs_outbox for efficiency
    # Only indexes unprocessed items, keeping the index small and fast
    op.create_index(
        "idx_audit_outbox_unprocessed",
        "audit_logs_outbox",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("processed = false"),
    )


def downgrade() -> None:
    """Drop audit logging tables and partitions."""

    # Drop audit_logs_outbox
    op.drop_index("idx_audit_outbox_unprocessed", table_name="audit_logs_outbox")
    op.drop_table("audit_logs_outbox")

    # Drop audit_logs partitions and parent table
    # Note: Dropping parent table automatically drops all partitions
    op.drop_index("idx_audit_logs_user_timestamp", table_name="audit_logs")
    op.drop_index("idx_audit_logs_resource", table_name="audit_logs")
    op.drop_index("idx_audit_logs_org_timestamp", table_name="audit_logs")
    op.drop_index("idx_audit_logs_action", table_name="audit_logs")
    op.drop_table("audit_logs")
