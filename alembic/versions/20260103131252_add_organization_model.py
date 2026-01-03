"""Add organization model for multi-tenancy

Revision ID: 20260103131252
Revises: 20260103100000
Create Date: 2026-01-03 13:12:52

This migration adds:
1. organization table - Tenant/organization entity
2. organization_member table - User membership with roles
3. api_key table - Organization-scoped API keys
4. org_id column to assistant, thread, runs tables (nullable for backward compat)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic
revision = "20260103131252"
down_revision = "20260103100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add organization model and org_id to existing tables."""

    # 1. Create organization table
    op.create_table(
        "organization",
        sa.Column(
            "org_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "settings",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
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
    )
    op.create_index("idx_organization_slug", "organization", ["slug"], unique=True)
    op.create_index("idx_organization_created_at", "organization", ["created_at"])

    # 2. Create organization_member table
    op.create_table(
        "organization_member",
        sa.Column(
            "id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'member'"),
        ),
        sa.Column("invited_by", sa.Text(), nullable=True),
        sa.Column(
            "joined_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.org_id"],
            name="fk_org_member_org_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_org_member_org_id", "organization_member", ["org_id"])
    op.create_index("idx_org_member_user_id", "organization_member", ["user_id"])
    op.create_index(
        "idx_org_member_org_user",
        "organization_member",
        ["org_id", "user_id"],
        unique=True,
    )

    # 3. Create api_key table
    op.create_table(
        "api_key",
        sa.Column(
            "key_id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("key_prefix", sa.Text(), nullable=False),
        sa.Column(
            "scopes",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.org_id"],
            name="fk_api_key_org_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_api_key_org_id", "api_key", ["org_id"])
    op.create_index("idx_api_key_hash", "api_key", ["key_hash"], unique=True)
    op.create_index("idx_api_key_prefix", "api_key", ["key_prefix"])

    # 4. Add org_id to existing tables (nullable for backward compatibility)

    # 4.1 Add org_id to assistant table
    op.add_column("assistant", sa.Column("org_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_assistant_org_id",
        "assistant",
        "organization",
        ["org_id"],
        ["org_id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_assistant_org_id", "assistant", ["org_id"])
    op.create_index("idx_assistant_org_user", "assistant", ["org_id", "user_id"])

    # 4.2 Add org_id to thread table
    op.add_column("thread", sa.Column("org_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_thread_org_id",
        "thread",
        "organization",
        ["org_id"],
        ["org_id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_thread_org_id", "thread", ["org_id"])
    op.create_index("idx_thread_org_user", "thread", ["org_id", "user_id"])

    # 4.3 Add org_id to runs table
    op.add_column("runs", sa.Column("org_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_runs_org_id",
        "runs",
        "organization",
        ["org_id"],
        ["org_id"],
        ondelete="SET NULL",
    )
    op.create_index("idx_runs_org_id", "runs", ["org_id"])
    op.create_index("idx_runs_org_thread", "runs", ["org_id", "thread_id"])


def downgrade() -> None:
    """Remove organization model and org_id from existing tables."""

    # Remove org_id from runs
    op.drop_index("idx_runs_org_thread", table_name="runs")
    op.drop_index("idx_runs_org_id", table_name="runs")
    op.drop_constraint("fk_runs_org_id", "runs", type_="foreignkey")
    op.drop_column("runs", "org_id")

    # Remove org_id from thread
    op.drop_index("idx_thread_org_user", table_name="thread")
    op.drop_index("idx_thread_org_id", table_name="thread")
    op.drop_constraint("fk_thread_org_id", "thread", type_="foreignkey")
    op.drop_column("thread", "org_id")

    # Remove org_id from assistant
    op.drop_index("idx_assistant_org_user", table_name="assistant")
    op.drop_index("idx_assistant_org_id", table_name="assistant")
    op.drop_constraint("fk_assistant_org_id", "assistant", type_="foreignkey")
    op.drop_column("assistant", "org_id")

    # Drop api_key table
    op.drop_index("idx_api_key_prefix", table_name="api_key")
    op.drop_index("idx_api_key_hash", table_name="api_key")
    op.drop_index("idx_api_key_org_id", table_name="api_key")
    op.drop_table("api_key")

    # Drop organization_member table
    op.drop_index("idx_org_member_org_user", table_name="organization_member")
    op.drop_index("idx_org_member_user_id", table_name="organization_member")
    op.drop_index("idx_org_member_org_id", table_name="organization_member")
    op.drop_table("organization_member")

    # Drop organization table
    op.drop_index("idx_organization_created_at", table_name="organization")
    op.drop_index("idx_organization_slug", table_name="organization")
    op.drop_table("organization")
