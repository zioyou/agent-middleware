"""Add feature flags tables

Revision ID: 20260105120000
Revises: 20260105110000
Create Date: 2026-01-05 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "20260105120000"
down_revision: str = "20260105110000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column(
            "flag_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "value_type",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'boolean'"),
        ),
        sa.Column(
            "default_value",
            JSONB,
            server_default=sa.text("'false'::jsonb"),
        ),
        sa.Column(
            "enabled_value",
            JSONB,
            server_default=sa.text("'true'::jsonb"),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_killswitch",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column(
            "rollout",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("targeting", JSONB, nullable=True),
        sa.Column(
            "tags",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column(
            "metadata",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
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
            name="fk_feature_flags_org_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "key", name="uq_feature_flag_org_key"),
    )
    op.create_index("idx_feature_flags_org_id", "feature_flags", ["org_id"])
    op.create_index("idx_feature_flags_key", "feature_flags", ["key"])
    op.create_index("idx_feature_flags_status", "feature_flags", ["org_id", "status"])
    op.create_index(
        "idx_feature_flags_tags",
        "feature_flags",
        ["tags"],
        postgresql_using="gin",
    )
    op.create_index(
        "idx_feature_flags_active",
        "feature_flags",
        ["org_id", "enabled"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "idx_feature_flags_killswitch",
        "feature_flags",
        ["org_id", "is_killswitch"],
        postgresql_where=sa.text("is_killswitch = true"),
    )

    op.create_table(
        "feature_flag_overrides",
        sa.Column(
            "override_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("flag_id", sa.Text(), nullable=False),
        sa.Column("flag_key", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
            ["flag_id"],
            ["feature_flags.flag_id"],
            name="fk_feature_flag_overrides_flag_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.org_id"],
            name="fk_feature_flag_overrides_org_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "flag_id",
            "org_id",
            "scope",
            "target_id",
            name="uq_feature_flag_override",
        ),
    )
    op.create_index(
        "idx_feature_flag_overrides_flag_id",
        "feature_flag_overrides",
        ["flag_id"],
    )
    op.create_index(
        "idx_feature_flag_overrides_org_id",
        "feature_flag_overrides",
        ["org_id"],
    )
    op.create_index(
        "idx_feature_flag_overrides_scope",
        "feature_flag_overrides",
        ["flag_id", "org_id", "scope"],
    )
    op.create_index(
        "idx_feature_flag_overrides_target",
        "feature_flag_overrides",
        ["flag_id", "org_id", "target_id"],
    )
    op.create_index(
        "idx_feature_flag_overrides_active",
        "feature_flag_overrides",
        ["flag_id", "org_id", "enabled"],
        # Note: Changed to filter by enabled=true and non-expiring records only
        # Original included 'expires_at > NOW()' but NOW() is not IMMUTABLE
        postgresql_where=sa.text("enabled = true AND expires_at IS NULL"),
    )

    op.create_table(
        "feature_flag_change_logs",
        sa.Column(
            "event_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("flag_id", sa.Text(), nullable=False),
        sa.Column("flag_key", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("changed_by", sa.Text(), nullable=True),
        sa.Column("previous_value", JSONB, nullable=True),
        sa.Column("new_value", JSONB, nullable=True),
        sa.Column(
            "metadata",
            JSONB,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["flag_id"],
            ["feature_flags.flag_id"],
            name="fk_feature_flag_change_logs_flag_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_feature_flag_change_logs_flag_id",
        "feature_flag_change_logs",
        ["flag_id"],
    )
    op.create_index(
        "idx_feature_flag_change_logs_org_ts",
        "feature_flag_change_logs",
        ["org_id", "timestamp"],
    )
    op.create_index(
        "idx_feature_flag_change_logs_event_type",
        "feature_flag_change_logs",
        ["flag_id", "event_type"],
    )
    op.create_index(
        "idx_feature_flag_change_logs_changed_by",
        "feature_flag_change_logs",
        ["changed_by", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("idx_feature_flag_change_logs_changed_by", table_name="feature_flag_change_logs")
    op.drop_index("idx_feature_flag_change_logs_event_type", table_name="feature_flag_change_logs")
    op.drop_index("idx_feature_flag_change_logs_org_ts", table_name="feature_flag_change_logs")
    op.drop_index("idx_feature_flag_change_logs_flag_id", table_name="feature_flag_change_logs")
    op.drop_table("feature_flag_change_logs")

    op.drop_index("idx_feature_flag_overrides_active", table_name="feature_flag_overrides")
    op.drop_index("idx_feature_flag_overrides_target", table_name="feature_flag_overrides")
    op.drop_index("idx_feature_flag_overrides_scope", table_name="feature_flag_overrides")
    op.drop_index("idx_feature_flag_overrides_org_id", table_name="feature_flag_overrides")
    op.drop_index("idx_feature_flag_overrides_flag_id", table_name="feature_flag_overrides")
    op.drop_table("feature_flag_overrides")

    op.drop_index("idx_feature_flags_killswitch", table_name="feature_flags")
    op.drop_index("idx_feature_flags_active", table_name="feature_flags")
    op.drop_index("idx_feature_flags_tags", table_name="feature_flags")
    op.drop_index("idx_feature_flags_status", table_name="feature_flags")
    op.drop_index("idx_feature_flags_key", table_name="feature_flags")
    op.drop_index("idx_feature_flags_org_id", table_name="feature_flags")
    op.drop_table("feature_flags")
