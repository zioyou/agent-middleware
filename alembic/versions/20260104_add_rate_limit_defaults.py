"""Add rate limit defaults to organizations

기존 Organization에 rate_limits 및 quotas 기본 설정을 추가합니다.

Revision ID: 4c8e2f1a9b73
Revises: 2b7f3c1d4a9e
Create Date: 2026-01-04 12:30:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "4c8e2f1a9b73"
down_revision = "2b7f3c1d4a9e"  # RLS policies migration
branch_labels = None
depends_on = None


# 기본 Rate Limit 설정
DEFAULT_RATE_LIMITS = {
    "requests_per_hour": 10000,
    "runs_per_hour": 1000,
    "streaming_per_hour": 200,
    "enabled": True,
}

# 기본 쿼터 설정
DEFAULT_QUOTAS = {
    "max_threads": 10000,
    "max_assistants": 100,
    "max_runs_per_day": 5000,
}


def upgrade() -> None:
    """기존 Organization에 rate_limits 및 quotas 기본 설정 추가

    - rate_limits 설정이 없는 조직에 기본값 추가
    - quotas 설정이 없는 조직에 기본값 추가
    """
    # rate_limits 기본값 추가
    op.execute(f"""
        UPDATE organization
        SET settings = COALESCE(settings, '{{}}'::jsonb) || '{{
            "rate_limits": {{
                "requests_per_hour": {DEFAULT_RATE_LIMITS["requests_per_hour"]},
                "runs_per_hour": {DEFAULT_RATE_LIMITS["runs_per_hour"]},
                "streaming_per_hour": {DEFAULT_RATE_LIMITS["streaming_per_hour"]},
                "enabled": {str(DEFAULT_RATE_LIMITS["enabled"]).lower()}
            }}
        }}'::jsonb
        WHERE NOT COALESCE(settings, '{{}}'::jsonb) ? 'rate_limits'
    """)

    # quotas 기본값 추가
    op.execute(f"""
        UPDATE organization
        SET settings = COALESCE(settings, '{{}}'::jsonb) || '{{
            "quotas": {{
                "max_threads": {DEFAULT_QUOTAS["max_threads"]},
                "max_assistants": {DEFAULT_QUOTAS["max_assistants"]},
                "max_runs_per_day": {DEFAULT_QUOTAS["max_runs_per_day"]}
            }}
        }}'::jsonb
        WHERE NOT COALESCE(settings, '{{}}'::jsonb) ? 'quotas'
    """)


def downgrade() -> None:
    """rate_limits 및 quotas 설정 제거"""
    op.execute("""
        UPDATE organization
        SET settings = settings - 'rate_limits' - 'quotas'
        WHERE settings IS NOT NULL
    """)
