"""Add agent identity and credential tables

Revision ID: 20260104120000
Revises: 8a4f5e7c9d12
Create Date: 2026-01-04 12:00:00

This migration adds:
1. agent_identity table - Agent identities scoped to organizations
2. agent_credential table - Agent credentials (JWT issuer/API key metadata)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "20260104120000"
down_revision = "8a4f5e7c9d12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add agent identity and credential tables."""
    op.create_table(
        "agent_identity",
        sa.Column(
            "id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("org_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'active'"),
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
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organization.org_id"],
            name="fk_agent_identity_org_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_agent_identity_org_id", "agent_identity", ["org_id"])
    op.create_index("idx_agent_identity_status", "agent_identity", ["status"])
    op.create_index(
        "idx_agent_identity_org_name",
        "agent_identity",
        ["org_id", "name"],
    )

    op.create_table(
        "agent_credential",
        sa.Column(
            "id",
            sa.Text(),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()::text"),
        ),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("credential_type", sa.Text(), nullable=False),
        sa.Column(
            "credential_data",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_identity.id"],
            name="fk_agent_credential_agent_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_agent_credential_agent_id",
        "agent_credential",
        ["agent_id"],
    )
    op.create_index(
        "idx_agent_credential_fingerprint",
        "agent_credential",
        ["fingerprint"],
        unique=True,
    )
    op.create_index(
        "idx_agent_credential_type",
        "agent_credential",
        ["credential_type"],
    )


def downgrade() -> None:
    """Remove agent identity and credential tables."""
    op.drop_index("idx_agent_credential_type", table_name="agent_credential")
    op.drop_index("idx_agent_credential_fingerprint", table_name="agent_credential")
    op.drop_index("idx_agent_credential_agent_id", table_name="agent_credential")
    op.drop_table("agent_credential")

    op.drop_index("idx_agent_identity_org_name", table_name="agent_identity")
    op.drop_index("idx_agent_identity_status", table_name="agent_identity")
    op.drop_index("idx_agent_identity_org_id", table_name="agent_identity")
    op.drop_table("agent_identity")
