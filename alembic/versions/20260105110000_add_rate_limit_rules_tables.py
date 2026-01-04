"""Add rate limit rules tables (DB-controlled rate limiting)

Revision ID: 20260105110000
Revises: 20260105100000
Create Date: 2026-01-05 11:00:00.000000

This migration adds:
1. rate_limit_rules table - Dynamic rate limit rule configurations
2. rate_limit_history table - Rate limit check history for analytics
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260105110000"
down_revision: str = "20260105100000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_rules",
        sa.Column(
            "rule_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("endpoint_pattern", sa.Text(), nullable=True),
        sa.Column("requests_per_window", sa.Integer(), nullable=False),
        sa.Column(
            "window_size",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'hour'"),
        ),
        sa.Column("burst_limit", sa.Integer(), nullable=True),
        sa.Column("burst_window", sa.Text(), nullable=True),
        sa.Column(
            "action",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'reject'"),
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.Text(), nullable=True),
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
            ["org_id"],
            ["organization.org_id"],
            name="fk_rate_limit_rules_org_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "name", name="uq_rate_limit_rule_org_name"),
    )
    op.create_index("idx_rate_limit_rules_org_id", "rate_limit_rules", ["org_id"])
    op.create_index(
        "idx_rate_limit_rules_target",
        "rate_limit_rules",
        ["org_id", "target_type", "target_id"],
    )
    op.create_index(
        "idx_rate_limit_rules_enabled",
        "rate_limit_rules",
        ["org_id", "enabled"],
    )
    op.create_index(
        "idx_rate_limit_rules_priority",
        "rate_limit_rules",
        ["org_id", "priority"],
    )
    op.create_index(
        "idx_rate_limit_rules_active",
        "rate_limit_rules",
        ["org_id", "enabled"],
        postgresql_where=sa.text("enabled = true AND (expires_at IS NULL OR expires_at > NOW())"),
    )

    op.create_table(
        "rate_limit_history",
        sa.Column(
            "id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.Text(), nullable=True),
        sa.Column("rule_name", sa.Text(), nullable=True),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.Column("api_key_id", sa.Text(), nullable=True),
        sa.Column("endpoint", sa.Text(), nullable=True),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("current_count", sa.Integer(), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("action_taken", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["rate_limit_rules.rule_id"],
            name="fk_rate_limit_history_rule_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "idx_rate_limit_history_org_ts",
        "rate_limit_history",
        ["org_id", "timestamp"],
    )
    op.create_index(
        "idx_rate_limit_history_rule_ts",
        "rate_limit_history",
        ["rule_id", "timestamp"],
    )
    op.create_index(
        "idx_rate_limit_history_user_ts",
        "rate_limit_history",
        ["org_id", "user_id", "timestamp"],
    )
    op.create_index(
        "idx_rate_limit_history_violations",
        "rate_limit_history",
        ["org_id", "timestamp"],
        postgresql_where=sa.text("allowed = false"),
    )


def downgrade() -> None:
    op.drop_index("idx_rate_limit_history_violations", table_name="rate_limit_history")
    op.drop_index("idx_rate_limit_history_user_ts", table_name="rate_limit_history")
    op.drop_index("idx_rate_limit_history_rule_ts", table_name="rate_limit_history")
    op.drop_index("idx_rate_limit_history_org_ts", table_name="rate_limit_history")
    op.drop_table("rate_limit_history")

    op.drop_index("idx_rate_limit_rules_active", table_name="rate_limit_rules")
    op.drop_index("idx_rate_limit_rules_priority", table_name="rate_limit_rules")
    op.drop_index("idx_rate_limit_rules_enabled", table_name="rate_limit_rules")
    op.drop_index("idx_rate_limit_rules_target", table_name="rate_limit_rules")
    op.drop_index("idx_rate_limit_rules_org_id", table_name="rate_limit_rules")
    op.drop_table("rate_limit_rules")
