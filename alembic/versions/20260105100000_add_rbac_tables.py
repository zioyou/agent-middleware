"""Add RBAC (Role-Based Access Control) tables

Revision ID: 20260105100000
Revises: 20260104150000
Create Date: 2026-01-05 10:00:00.000000

This migration adds:
1. role_definitions table - Role definitions with permissions (system and custom roles)
2. user_custom_permissions table - User-specific permission grants/denials
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "20260105100000"
down_revision: str = "20260104150000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "role_definitions",
        sa.Column(
            "id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("org_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "permissions",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
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
            name="fk_role_definitions_org_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("org_id", "name", name="uq_role_org_name"),
    )
    op.create_index("idx_role_definitions_org_id", "role_definitions", ["org_id"])
    op.create_index("idx_role_definitions_name", "role_definitions", ["name"])
    op.create_index("idx_role_definitions_is_system", "role_definitions", ["is_system"])

    op.create_table(
        "user_custom_permissions",
        sa.Column(
            "id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column(
            "granted_permissions",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "denied_permissions",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("granted_by", sa.Text(), nullable=True),
        sa.Column(
            "granted_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.org_id"],
            name="fk_user_custom_perms_org_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "org_id", name="uq_user_org_custom_perms"),
    )
    op.create_index(
        "idx_user_custom_perms_user_org",
        "user_custom_permissions",
        ["user_id", "org_id"],
    )
    op.create_index(
        "idx_user_custom_perms_org_id",
        "user_custom_permissions",
        ["org_id"],
    )
    op.create_index(
        "idx_user_custom_perms_active",
        "user_custom_permissions",
        ["user_id", "org_id"],
        postgresql_where=sa.text("expires_at IS NULL OR expires_at > NOW()"),
    )


def downgrade() -> None:
    op.drop_index("idx_user_custom_perms_active", table_name="user_custom_permissions")
    op.drop_index("idx_user_custom_perms_org_id", table_name="user_custom_permissions")
    op.drop_index("idx_user_custom_perms_user_org", table_name="user_custom_permissions")
    op.drop_table("user_custom_permissions")

    op.drop_index("idx_role_definitions_is_system", table_name="role_definitions")
    op.drop_index("idx_role_definitions_name", table_name="role_definitions")
    op.drop_index("idx_role_definitions_org_id", table_name="role_definitions")
    op.drop_table("role_definitions")
