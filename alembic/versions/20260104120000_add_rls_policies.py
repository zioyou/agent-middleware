"""Enable RLS policies for tenant-scoped metadata tables.

Revision ID: 2b7f3c1d4a9e
Revises: 8a4f5e7c9d12
Create Date: 2026-01-04 12:00:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "2b7f3c1d4a9e"
down_revision = "8a4f5e7c9d12"
branch_labels = None
depends_on = None


_TENANT_CONDITION = """
(
    current_setting('app.rls_bypass', true) = 'true'
    OR user_id = NULLIF(current_setting('app.current_user_id', true), '')
    OR org_id = NULLIF(current_setting('app.current_org_id', true), '')
)
"""

_AUDIT_CONDITION = """
(
    current_setting('app.rls_bypass', true) = 'true'
    OR org_id = NULLIF(current_setting('app.current_org_id', true), '')
)
"""


def upgrade() -> None:
    """Enable RLS and create tenant-scoped policies."""
    op.execute("ALTER TABLE assistant ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE thread ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY assistant_rls_policy ON assistant
        USING {_TENANT_CONDITION}
        WITH CHECK {_TENANT_CONDITION}
        """
    )
    op.execute(
        f"""
        CREATE POLICY thread_rls_policy ON thread
        USING {_TENANT_CONDITION}
        WITH CHECK {_TENANT_CONDITION}
        """
    )
    op.execute(
        f"""
        CREATE POLICY runs_rls_policy ON runs
        USING {_TENANT_CONDITION}
        WITH CHECK {_TENANT_CONDITION}
        """
    )
    op.execute(
        f"""
        CREATE POLICY audit_logs_rls_policy ON audit_logs
        USING {_AUDIT_CONDITION}
        WITH CHECK {_AUDIT_CONDITION}
        """
    )


def downgrade() -> None:
    """Drop RLS policies and disable row-level security."""
    op.execute("DROP POLICY IF EXISTS assistant_rls_policy ON assistant")
    op.execute("DROP POLICY IF EXISTS thread_rls_policy ON thread")
    op.execute("DROP POLICY IF EXISTS runs_rls_policy ON runs")
    op.execute("DROP POLICY IF EXISTS audit_logs_rls_policy ON audit_logs")

    op.execute("ALTER TABLE assistant DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE thread DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE runs DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_logs DISABLE ROW LEVEL SECURITY")
