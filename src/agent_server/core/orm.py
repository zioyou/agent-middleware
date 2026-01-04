"""Agent Protocol 메타데이터 영속성을 위한 SQLAlchemy ORM 설정

이 모듈은 Open LangGraph의 핵심 데이터베이스 모델을 정의합니다.
LangGraph는 자체 체크포인터로 대화 상태를 관리하고,
이 모듈의 ORM 모델은 Agent Protocol 메타데이터만 저장합니다.

주요 구성 요소:
• `Base` - 모든 ORM 모델의 기반 클래스 (declarative base)
• `Organization` - 조직(테넌트) 정의 (멀티테넌시)
• `OrganizationMember` - 조직 멤버십 (역할 기반)
• `APIKey` - 조직별 API 키 관리
• `AgentIdentity` - 에이전트 신원 관리 (A2A 인증)
• `AgentCredential` - 에이전트 자격 증명 관리 (JWT/API 키)
• `Assistant` - 어시스턴트 정의 (그래프 ID, 설정, 사용자 정보)
• `AssistantVersion` - 어시스턴트 버전 이력 추적
• `Thread` - 대화 스레드 메타데이터 (상태, 사용자 정보)
• `Run` - 실행 기록 (입력/출력, 상태, 타임스탬프)
• `RunEvent` - SSE 이벤트 저장 (스트리밍 재생용)
• `async_session_maker` - AsyncSession 팩토리
• `get_session` - FastAPI 라우터용 의존성 헬퍼

사용법:
    from ...core.orm import get_session, Assistant

    @router.get("/assistants")
    async def list_assistants(session: AsyncSession = Depends(get_session)):
        result = await session.execute(select(Assistant))
        return result.scalars().all()
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy import (
    TIMESTAMP,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .rls import clear_rls_context, set_rls_context


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""

    pass


# ---------------------------------------------------------------------------
# Organization Models (Multi-Tenancy)
# ---------------------------------------------------------------------------


class Organization(Base):
    """조직(테넌트) ORM 모델

    조직은 멀티테넌시의 기본 단위입니다. 사용자는 여러 조직에 속할 수 있으며,
    각 조직은 독립적인 리소스(Assistant, Thread, Run)를 가집니다.

    주요 필드:
    - org_id: 고유 식별자 (UUID, DB에서 자동 생성)
    - name: 조직 이름 (표시용)
    - slug: URL 친화적 식별자 (자동 생성, 고유)
    - settings: 조직 설정 (rate limits, quotas 등)
    - metadata_dict: 추가 메타데이터 (JSONB)
    """

    __tablename__ = "organization"

    org_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    metadata_dict: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), name="metadata"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("idx_organization_slug", "slug", unique=True),
        Index("idx_organization_created_at", "created_at"),
    )


class OrganizationMember(Base):
    """조직 멤버십 ORM 모델

    조직과 사용자 간의 멤버십을 관리합니다.
    각 멤버는 역할(role)을 가지며, RBAC 권한 검사에 사용됩니다.

    역할:
    - owner: 전체 권한 (조직 삭제 가능)
    - admin: 멤버/설정 관리
    - member: 리소스 생성/수정
    - viewer: 읽기 전용

    복합 고유 키: (org_id, user_id)
    """

    __tablename__ = "organization_member"

    id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("uuid_generate_v4()::text"))
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'member'"))
    invited_by: Mapped[str | None] = mapped_column(Text)
    joined_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("idx_org_member_org_id", "org_id"),
        Index("idx_org_member_user_id", "user_id"),
        Index("idx_org_member_org_user", "org_id", "user_id", unique=True),
    )


class APIKey(Base):
    """조직별 API 키 ORM 모델

    조직 단위의 API 키를 관리합니다. 키 자체는 해시로 저장되며,
    생성 시에만 전문이 반환됩니다.

    주요 필드:
    - key_id: 고유 식별자 (UUID)
    - org_id: 소속 조직 (FK, CASCADE DELETE)
    - key_hash: SHA-256 해시 (검증용)
    - key_prefix: 표시용 접두사 (예: "olg_xxxxx")
    - scopes: 권한 범위 (예: ["assistants:read", "runs:write"])
    """

    __tablename__ = "api_key"

    key_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index("idx_api_key_org_id", "org_id"),
        Index("idx_api_key_hash", "key_hash", unique=True),
        Index("idx_api_key_prefix", "key_prefix"),
    )


# ---------------------------------------------------------------------------
# Agent Authentication Models
# ---------------------------------------------------------------------------


class AgentIdentity(Base):
    """에이전트 신원 ORM 모델

    에이전트는 조직 내에서 고유한 신원을 가지며,
    A2A 인증 및 자격 증명 관리의 기준이 됩니다.
    """

    __tablename__ = "agent_identity"

    id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("uuid_generate_v4()::text"))
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    metadata_dict: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), name="metadata"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("idx_agent_identity_org_id", "org_id"),
        Index("idx_agent_identity_status", "status"),
        Index("idx_agent_identity_org_name", "org_id", "name"),
    )


class AgentCredential(Base):
    """에이전트 자격 증명 ORM 모델

    JWT issuer 또는 API 키 기반의 자격 증명을 저장합니다.
    """

    __tablename__ = "agent_credential"

    id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("uuid_generate_v4()::text"))
    agent_id: Mapped[str] = mapped_column(
        Text, ForeignKey("agent_identity.id", ondelete="CASCADE"), nullable=False
    )
    credential_type: Mapped[str] = mapped_column(Text, nullable=False)
    credential_data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index("idx_agent_credential_agent_id", "agent_id"),
        Index("idx_agent_credential_fingerprint", "fingerprint", unique=True),
        Index("idx_agent_credential_type", "credential_type"),
    )


# ---------------------------------------------------------------------------
# RBAC (Role-Based Access Control) Models
# ---------------------------------------------------------------------------


class RoleDefinition(Base):
    """역할 정의 ORM 모델

    조직 내에서 사용자에게 할당할 수 있는 역할을 정의합니다.
    각 역할은 권한 문자열 목록을 가지며, 권한 검사에 사용됩니다.

    시스템 역할 (is_system=True):
    - owner: 전체 권한 ("*")
    - admin: 멤버/설정 관리 권한
    - developer: AI 에이전트 및 워크플로우 관리
    - viewer: 읽기 전용 접근
    - api_user: 제한된 API 접근

    주요 필드:
    - id: 고유 식별자 (UUID, DB에서 자동 생성)
    - org_id: 소속 조직 (NULL이면 시스템 역할)
    - name: 역할 이름 (조직 내 고유)
    - display_name: 표시용 이름
    - description: 역할 설명
    - permissions: 권한 문자열 배열 (예: ["assistants:read", "threads:*"])
    - is_system: 시스템 역할 여부 (시스템 역할은 삭제/수정 불가)
    - priority: 우선순위 (높을수록 더 많은 권한)
    """

    __tablename__ = "role_definitions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("uuid_generate_v4()::text"))
    org_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_role_org_name"),
        Index("idx_role_definitions_org_id", "org_id"),
        Index("idx_role_definitions_name", "name"),
        Index("idx_role_definitions_is_system", "is_system"),
    )


class UserCustomPermissions(Base):
    """사용자 커스텀 권한 ORM 모델

    역할 기반 권한 외에 사용자에게 개별적으로 부여/거부하는 권한을 관리합니다.
    denied_permissions는 granted_permissions와 역할 권한을 모두 오버라이드합니다.

    권한 해결 순서:
    1. 사용자의 역할 권한 가져오기
    2. granted_permissions 추가
    3. denied_permissions 제거 (최종 오버라이드)

    주요 필드:
    - id: 고유 식별자 (UUID, DB에서 자동 생성)
    - user_id: 사용자 ID
    - org_id: 소속 조직
    - granted_permissions: 추가로 부여된 권한 배열
    - denied_permissions: 명시적으로 거부된 권한 배열 (오버라이드)
    - granted_by: 권한을 부여한 사용자 ID
    - granted_at: 권한 부여 시간
    - expires_at: 권한 만료 시간 (선택적)
    - reason: 권한 부여/거부 사유
    """

    __tablename__ = "user_custom_permissions"

    id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("uuid_generate_v4()::text"))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="CASCADE"), nullable=False
    )
    granted_permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    denied_permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )
    granted_by: Mapped[str | None] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_user_org_custom_perms"),
        Index("idx_user_custom_perms_user_org", "user_id", "org_id"),
        Index("idx_user_custom_perms_org_id", "org_id"),
        # Partial index for non-expired permissions
        Index(
            "idx_user_custom_perms_active",
            "user_id",
            "org_id",
            postgresql_where=text("expires_at IS NULL OR expires_at > NOW()"),
        ),
    )


# ---------------------------------------------------------------------------
# Rate Limiting Models (DB-Controlled)
# ---------------------------------------------------------------------------


class RateLimitRule(Base):
    """Rate Limit 규칙 ORM 모델

    DB 기반의 동적 rate limiting 규칙을 정의합니다.
    환경 변수 기반 설정(core/rate_limiter.py)과 달리,
    조직/사용자/엔드포인트별 세밀한 제어가 가능합니다.

    규칙 우선순위 (priority):
    - global=0: 시스템 전체 기본값
    - org=100: 조직 수준
    - endpoint=200: 엔드포인트 패턴
    - user=300: 특정 사용자
    - api_key=400: 특정 API 키

    주요 필드:
    - rule_id: 고유 식별자 (UUID, DB 자동 생성)
    - org_id: 소속 조직 (FK)
    - name: 규칙 이름
    - target_type: 적용 대상 유형 (global/org/user/api_key/endpoint)
    - target_id: 대상 식별자 (user_id, api_key_id 등)
    - endpoint_pattern: 엔드포인트 패턴 (glob 지원: /runs/*, /threads/*/runs)
    - requests_per_window: 윈도우당 최대 요청 수
    - window_size: 시간 윈도우 (second/minute/hour/day)
    - burst_limit: 버스트 제한 (선택적)
    - action: 초과 시 행동 (reject/throttle/log_only)
    - priority: 규칙 우선순위 (높을수록 우선)
    """

    __tablename__ = "rate_limit_rules"

    rule_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[str | None] = mapped_column(Text)
    endpoint_pattern: Mapped[str | None] = mapped_column(Text)
    requests_per_window: Mapped[int] = mapped_column(Integer, nullable=False)
    window_size: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'hour'"))
    burst_limit: Mapped[int | None] = mapped_column(Integer)
    burst_window: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'reject'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    metadata_dict: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), name="metadata"
    )
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_rate_limit_rule_org_name"),
        Index("idx_rate_limit_rules_org_id", "org_id"),
        Index("idx_rate_limit_rules_target", "org_id", "target_type", "target_id"),
        Index("idx_rate_limit_rules_enabled", "org_id", "enabled"),
        Index("idx_rate_limit_rules_priority", "org_id", "priority"),
        Index(
            "idx_rate_limit_rules_active",
            "org_id",
            "enabled",
            postgresql_where=text("enabled = true AND (expires_at IS NULL OR expires_at > NOW())"),
        ),
    )


class RateLimitHistory(Base):
    """Rate Limit 이력 ORM 모델

    rate limit 체크 결과와 위반 사항을 기록합니다.
    분석 및 모니터링에 활용됩니다.

    레코드 유형:
    - hit: 정상 체크 (allowed=true)
    - violation: 제한 초과 (allowed=false)

    집계를 위한 인덱스:
    - (org_id, timestamp): 조직별 시간순 조회
    - (rule_id, timestamp): 규칙별 시간순 조회
    - (org_id, user_id, timestamp): 사용자별 조회

    보존 정책:
    - 기본 30일 보존 (설정 가능)
    - 파티셔닝은 선택적 (대용량 시)
    """

    __tablename__ = "rate_limit_history"

    id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("uuid_generate_v4()::text"))
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("rate_limit_rules.rule_id", ondelete="SET NULL")
    )
    rule_name: Mapped[str | None] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )
    user_id: Mapped[str | None] = mapped_column(Text)
    api_key_id: Mapped[str | None] = mapped_column(Text)
    endpoint: Mapped[str | None] = mapped_column(Text)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    current_count: Mapped[int] = mapped_column(Integer, nullable=False)
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False, name="limit")
    action_taken: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_rate_limit_history_org_ts", "org_id", "timestamp"),
        Index("idx_rate_limit_history_rule_ts", "rule_id", "timestamp"),
        Index("idx_rate_limit_history_user_ts", "org_id", "user_id", "timestamp"),
        Index(
            "idx_rate_limit_history_violations",
            "org_id",
            "timestamp",
            postgresql_where=text("allowed = false"),
        ),
    )


# ---------------------------------------------------------------------------
# Feature Flags Models
# ---------------------------------------------------------------------------


class FeatureFlag(Base):
    """Feature Flag ORM 모델

    동적 기능 토글을 위한 기능 플래그를 정의합니다.
    점진적 롤아웃, A/B 테스트, 킬스위치 등을 지원합니다.

    플래그 상태:
    - active: 플래그가 활성화되어 평가됨
    - disabled: 비활성화 (기본값/off 반환)
    - archived: 아카이브됨 (소프트 삭제)

    값 유형:
    - boolean: True/False 토글
    - string: 문자열 값 (예: 변형 이름)
    - number: 숫자 값 (int 또는 float)
    - json: 임의의 JSON 객체

    주요 필드:
    - flag_id: 고유 식별자 (UUID, DB 자동 생성)
    - org_id: 소속 조직 ('global'이면 시스템 플래그)
    - key: 플래그 키 (조직 내 고유)
    - name: 표시용 이름
    - value_type: 값 유형
    - default_value: 기본값 (off일 때)
    - enabled_value: 활성화 값 (on일 때)
    - rollout: 점진적 롤아웃 설정 (JSONB)
    - targeting: 타겟팅 규칙 (JSONB)
    """

    __tablename__ = "feature_flags"

    flag_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'boolean'"))
    default_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default=text("'false'::jsonb"))
    enabled_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default=text("'true'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_killswitch: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    rollout: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    targeting: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    metadata_dict: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), name="metadata"
    )
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_feature_flag_org_key"),
        Index("idx_feature_flags_org_id", "org_id"),
        Index("idx_feature_flags_key", "key"),
        Index("idx_feature_flags_status", "org_id", "status"),
        Index("idx_feature_flags_tags", "tags", postgresql_using="gin"),
        Index(
            "idx_feature_flags_active",
            "org_id",
            "enabled",
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "idx_feature_flags_killswitch",
            "org_id",
            "is_killswitch",
            postgresql_where=text("is_killswitch = true"),
        ),
    )


class FeatureFlagOverride(Base):
    """Feature Flag Override ORM 모델

    특정 조직 또는 사용자에 대한 플래그 값 오버라이드를 정의합니다.
    오버라이드는 기본 플래그 값보다 우선합니다.

    오버라이드 범위:
    - org: 조직 수준 (해당 조직의 모든 사용자)
    - user: 사용자 수준 (특정 사용자만)

    해결 순서 (첫 번째 일치 적용):
    1. 사용자별 오버라이드
    2. 조직별 오버라이드
    3. 전역 플래그 기본값

    주요 필드:
    - override_id: 고유 식별자 (UUID, DB 자동 생성)
    - flag_id: 오버라이드할 플래그 (FK)
    - org_id: 소속 조직
    - scope: 오버라이드 범위 (org/user)
    - target_id: 대상 ID (user scope일 때 user_id)
    - value: 오버라이드 값 (JSONB)
    """

    __tablename__ = "feature_flag_overrides"

    override_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    flag_id: Mapped[str] = mapped_column(
        Text, ForeignKey("feature_flags.flag_id", ondelete="CASCADE"), nullable=False
    )
    flag_key: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[str] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="CASCADE"), nullable=False
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)  # 'org' or 'user'
    target_id: Mapped[str | None] = mapped_column(Text)  # user_id for USER scope
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        # Unique constraint: one override per flag + scope + target combination
        UniqueConstraint("flag_id", "org_id", "scope", "target_id", name="uq_feature_flag_override"),
        Index("idx_feature_flag_overrides_flag_id", "flag_id"),
        Index("idx_feature_flag_overrides_org_id", "org_id"),
        Index("idx_feature_flag_overrides_scope", "flag_id", "org_id", "scope"),
        Index("idx_feature_flag_overrides_target", "flag_id", "org_id", "target_id"),
        Index(
            "idx_feature_flag_overrides_active",
            "flag_id",
            "org_id",
            "enabled",
            postgresql_where=text("enabled = true AND (expires_at IS NULL OR expires_at > NOW())"),
        ),
    )


class FeatureFlagChangeLog(Base):
    """Feature Flag Change Log ORM 모델

    플래그 변경 이력을 기록합니다.
    감사 추적 및 변경 복구에 사용됩니다.

    이벤트 유형:
    - created: 플래그 생성
    - updated: 플래그 업데이트
    - enabled: 플래그 활성화
    - disabled: 플래그 비활성화
    - archived: 플래그 아카이브
    - override_added: 오버라이드 추가
    - override_updated: 오버라이드 업데이트
    - override_removed: 오버라이드 제거

    주요 필드:
    - event_id: 이벤트 고유 ID
    - flag_id: 변경된 플래그
    - event_type: 이벤트 유형
    - previous_value: 이전 값 (JSONB)
    - new_value: 새 값 (JSONB)
    - changed_by: 변경한 사용자
    """

    __tablename__ = "feature_flag_change_logs"

    event_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    flag_id: Mapped[str] = mapped_column(
        Text, ForeignKey("feature_flags.flag_id", ondelete="CASCADE"), nullable=False
    )
    flag_key: Mapped[str] = mapped_column(Text, nullable=False)
    org_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(Text)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metadata_dict: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), name="metadata"
    )
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
    )

    __table_args__ = (
        Index("idx_feature_flag_change_logs_flag_id", "flag_id"),
        Index("idx_feature_flag_change_logs_org_ts", "org_id", "timestamp"),
        Index("idx_feature_flag_change_logs_event_type", "flag_id", "event_type"),
        Index("idx_feature_flag_change_logs_changed_by", "changed_by", "timestamp"),
    )


# ---------------------------------------------------------------------------
# Core Agent Protocol Models
# ---------------------------------------------------------------------------


class Assistant(Base):
    """어시스턴트 정의 ORM 모델

    어시스턴트는 특정 LangGraph 그래프와 설정을 결합한 실행 가능한 엔티티입니다.
    사용자는 여러 어시스턴트를 생성하여 동일한 그래프를 다른 설정으로 실행할 수 있습니다.

    주요 필드:
    - assistant_id: 고유 식별자 (UUID, DB에서 자동 생성)
    - graph_id: 실행할 LangGraph 그래프 ID (open_langgraph.json에 정의)
    - name: 사용자가 지정한 어시스턴트 이름
    - config: LangGraph 실행 설정 (JSONB)
    - context: 그래프 런타임 컨텍스트 (JSONB)
    - version: 버전 번호 (기본값 1)
    - metadata_dict: 추가 메타데이터 (JSONB)
    - org_id: 소속 조직 (멀티테넌시, nullable for backward compatibility)
    """

    __tablename__ = "assistant"

    # TEXT 타입 PK, DB 측에서 uuid_generate_v4()로 자동 생성
    assistant_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    graph_id: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    # 조직 ID - 멀티테넌시 지원 (nullable for backward compatibility)
    org_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    metadata_dict: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), name="metadata"
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    # 성능 최적화를 위한 인덱스
    # - user_id: 사용자별 어시스턴트 조회 최적화
    # - (user_id, assistant_id): 고유성 보장
    # - (user_id, graph_id, config): 동일 설정 중복 방지
    # - org_id: 조직별 어시스턴트 조회 최적화
    __table_args__ = (
        Index("idx_assistant_user", "user_id"),
        Index("idx_assistant_user_assistant", "user_id", "assistant_id", unique=True),
        Index(
            "idx_assistant_user_graph_config",
            "user_id",
            "graph_id",
            "config",
            unique=True,
        ),
        Index("idx_assistant_org_id", "org_id"),
        Index("idx_assistant_org_user", "org_id", "user_id"),
    )


class AssistantVersion(Base):
    """어시스턴트 버전 이력 추적 ORM 모델

    어시스턴트가 업데이트될 때마다 이전 버전을 이 테이블에 보관합니다.
    사용자는 과거 버전으로 롤백하거나 변경 이력을 조회할 수 있습니다.

    복합 PK: (assistant_id, version)
    - assistant_id: 어시스턴트 식별자 (FK, CASCADE DELETE)
    - version: 버전 번호 (1, 2, 3, ...)
    """

    __tablename__ = "assistant_versions"

    assistant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("assistant.assistant_id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    graph_id: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    metadata_dict: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), name="metadata"
    )
    name: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Thread(Base):
    """대화 스레드 메타데이터 ORM 모델

    스레드는 하나의 대화 세션을 나타냅니다.
    실제 대화 메시지와 상태는 LangGraph 체크포인터에 저장되며,
    이 테이블은 스레드 상태(idle/busy/interrupted)와 메타데이터만 관리합니다.

    상태 종류:
    - idle: 대기 중 (실행 가능)
    - busy: 실행 중
    - interrupted: 중단됨 (Human-in-the-Loop)

    TTL (Time-to-Live) 전략:
    - delete: 만료 시 스레드 삭제
    - archive: 만료 시 스레드 아카이브 (추후 구현)

    주요 필드:
    - thread_id: 고유 식별자 (클라이언트가 생성)
    - status: 현재 상태
    - metadata_json: 어시스턴트/그래프 정보 등 (JSONB)
    - user_id: 소유자 (멀티테넌트 격리)
    - org_id: 소속 조직 (멀티테넌시, nullable for backward compatibility)
    - ttl_seconds: TTL 기간 (초)
    - ttl_strategy: 만료 전략 (delete/archive)
    - expires_at: 만료 시간
    """

    __tablename__ = "thread"

    thread_id: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'idle'"))
    # DB 컬럼명은 'metadata_json', ORM 속성도 'metadata_json'으로 매핑
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata_json", JSONB, server_default=text("'{}'::jsonb")
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    # 조직 ID - 멀티테넌시 지원 (nullable for backward compatibility)
    org_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    # TTL (Time-to-Live) 필드 - threads.update SDK 호환
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ttl_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)  # 'delete' | 'archive'
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # 성능 최적화 인덱스
    __table_args__ = (
        Index("idx_thread_user", "user_id"),
        Index("idx_thread_org_id", "org_id"),
        Index("idx_thread_org_user", "org_id", "user_id"),
        # TTL 만료 스레드 조회 최적화 (expires_at이 있는 경우만)
        Index(
            "idx_thread_expires_at",
            "expires_at",
            postgresql_where=text("expires_at IS NOT NULL"),
        ),
    )


class Run(Base):
    """실행 기록 ORM 모델

    Run은 특정 스레드에서 어시스턴트를 실행한 하나의 인스턴스입니다.
    입력, 출력, 상태, 타임스탬프 등 실행 메타데이터를 저장합니다.

    상태 종류:
    - pending: 대기 중
    - running: 실행 중
    - streaming: 스트리밍 중
    - completed: 성공 완료
    - failed: 실패
    - cancelled: 취소됨
    - interrupted: 중단됨 (HITL)

    주요 필드:
    - run_id: 고유 식별자 (UUID, DB 자동 생성)
    - thread_id: 소속 스레드 (FK, CASCADE DELETE)
    - assistant_id: 사용된 어시스턴트 (FK, CASCADE DELETE)
    - org_id: 소속 조직 (멀티테넌시, nullable for backward compatibility)
    - input: 실행 입력 데이터 (JSONB)
    - output: 실행 결과 (JSONB)
    - config: LangGraph 실행 설정 (JSONB)
    - context: 런타임 컨텍스트 (JSONB)
    - error_message: 오류 발생 시 메시지
    """

    __tablename__ = "runs"

    # TEXT 타입 PK, DB 측에서 uuid_generate_v4()로 자동 생성
    run_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    thread_id: Mapped[str] = mapped_column(
        Text, ForeignKey("thread.thread_id", ondelete="CASCADE"), nullable=False
    )
    assistant_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("assistant.assistant_id", ondelete="CASCADE")
    )
    # 조직 ID - 멀티테넌시 지원 (nullable for backward compatibility)
    org_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("organization.org_id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    input: Mapped[dict[str, Any] | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # config 컬럼: 일부 환경에서는 아직 없을 수 있어 nullable 설정
    # 마이그레이션으로 추가되면 이미 ORM에 정의되어 있음
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    # 성능 최적화 인덱스
    # - thread_id: 스레드별 실행 목록 조회
    # - user_id: 사용자별 실행 조회
    # - status: 상태별 필터링
    # - assistant_id: 어시스턴트별 실행 조회
    # - created_at: 시간순 정렬 최적화
    # - org_id: 조직별 실행 조회 최적화
    __table_args__ = (
        Index("idx_runs_thread_id", "thread_id"),
        Index("idx_runs_user", "user_id"),
        Index("idx_runs_status", "status"),
        Index("idx_runs_assistant_id", "assistant_id"),
        Index("idx_runs_created_at", "created_at"),
        Index("idx_runs_org_id", "org_id"),
        Index("idx_runs_org_thread", "org_id", "thread_id"),
    )


# ---------------------------------------------------------------------------
# Audit Logging Models
# ---------------------------------------------------------------------------


class AuditLogOutbox(Base):
    """감사 로그 Outbox 테이블 ORM 모델

    Outbox 패턴을 사용하여 감사 로그의 신뢰성을 보장합니다.
    미들웨어에서 즉시 INSERT하고, 백그라운드 작업이 파티션 테이블로 이동합니다.

    이 패턴의 장점:
    - 프로세스 크래시에도 데이터 손실 없음 (동기 DB 쓰기)
    - 비동기 처리의 성능 이점 유지 (배치 이동)
    - SELECT FOR UPDATE SKIP LOCKED으로 동시성 안전

    주요 필드:
    - id: 고유 식별자 (UUID, DB에서 자동 생성)
    - created_at: 생성 시간 (인덱스, 배치 처리 순서용)
    - payload: 전체 감사 로그 데이터 (JSONB)
    - processed: 처리 완료 여부 (배치 이동 후 삭제됨)
    """

    __tablename__ = "audit_logs_outbox"

    id: Mapped[str] = mapped_column(Text, primary_key=True, server_default=text("uuid_generate_v4()::text"))
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("now()"), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)

    __table_args__ = (
        # Partial index for efficiency: only track unprocessed items
        # This keeps the index small as most records become processed=true
        Index(
            "idx_audit_outbox_unprocessed",
            "created_at",
            postgresql_where=text("processed = false"),
        ),
    )


class AuditLog(Base):
    """감사 로그 메인 테이블 ORM 모델 (월별 파티셔닝)

    모든 API 요청에 대한 감사 로그를 저장하는 파티션 테이블입니다.
    Outbox 테이블에서 배치로 이동되어 저장됩니다.

    파티셔닝 전략:
    - RANGE 파티셔닝 (timestamp 기준)
    - 월별 파티션 자동 생성 (PartitionService)
    - 90일 이상 오래된 파티션 자동 삭제

    주요 필드 그룹:
    1. 식별자: id, timestamp (복합 PK, 파티션 키)
    2. 사용자: user_id, org_id (멀티테넌트 격리)
    3. 액션: action, resource_type, resource_id
    4. 요청: http_method, path, request_body, ip_address, user_agent
    5. 응답: status_code, response_summary, duration_ms
    6. 오류: error_message, error_class (예외 발생 시)
    7. 스트리밍: is_streaming (SSE 응답 여부)
    8. 메타데이터: metadata (추가 정보)

    인덱스 전략:
    - (org_id, timestamp): 조직별 시간순 조회
    - (user_id, timestamp): 사용자별 시간순 조회
    - (resource_type, resource_id): 리소스별 조회
    """

    __tablename__ = "audit_logs"

    # 복합 PK (파티셔닝 요구사항: 파티션 키가 PK에 포함되어야 함)
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), primary_key=True)

    # 사용자 정보
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    # NOTE: org_id intentionally has NO foreign key to organization table.
    # Audit logs must be immutable and survive organization deletion.
    # Multi-tenant isolation is enforced at the API layer via AuditLogFilters.
    org_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 액션 정보
    action: Mapped[str] = mapped_column(Text, nullable=False)  # CREATE, READ, UPDATE, DELETE, RUN
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)  # assistant, thread, run
    resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    # HTTP 요청 정보
    http_method: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 요청/응답 데이터
    request_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # 오류 정보 (Codex 피드백: error_class 추가)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_class: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 스트리밍 여부 (Codex 피드백: is_streaming 추가)
    is_streaming: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)

    # 추가 메타데이터
    metadata_dict: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), name="metadata"
    )

    __table_args__ = (
        # 조직별 시간순 조회 최적화 (멀티테넌트 필수)
        Index("idx_audit_logs_org_timestamp", "org_id", "timestamp"),
        # 사용자별 시간순 조회 최적화
        Index("idx_audit_logs_user_timestamp", "user_id", "timestamp"),
        # 리소스별 조회 최적화
        Index("idx_audit_logs_resource", "resource_type", "resource_id"),
        # 액션별 조회 (선택적)
        Index("idx_audit_logs_action", "action"),
        # 월별 파티셔닝 설정
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )


class RunEvent(Base):
    """실행 이벤트 저장 ORM 모델 (SSE 재생용)

    SSE(Server-Sent Events) 스트리밍 중 발생한 모든 이벤트를 저장합니다.
    클라이언트가 연결이 끊겼다가 재연결하면 저장된 이벤트를 재생할 수 있습니다.

    주요 필드:
    - id: 이벤트 고유 ID (형식: {run_id}_event_{seq})
    - run_id: 소속 실행 ID
    - seq: 시퀀스 번호 (정렬용)
    - event: 이벤트 타입 (values, messages, end 등)
    - data: 이벤트 페이로드 (JSONB)
    - created_at: 생성 시간

    정리 정책:
    - event_store 서비스가 주기적으로 오래된 이벤트 삭제 (기본 300초 이상)
    """

    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    # 성능 최적화 인덱스
    # - run_id: 실행별 이벤트 조회
    # - (run_id, seq): 시퀀스 기반 이벤트 재생 최적화
    __table_args__ = (
        Index("idx_run_events_run_id", "run_id"),
        Index("idx_run_events_seq", "run_id", "seq"),
    )


class Cron(Base):
    """Cron 작업 스케줄링 ORM 모델

    정기적으로 실행되어야 하는 에이전트 작업을 정의합니다.

    주요 필드:
    - cron_id: 고유 식별자 (UUID, DB 자동 생성)
    - assistant_id: 실행할 어시스턴트 (FK)
    - thread_id: 실행할 스레드 (FK, 선택사항)
    - user_id: 소유자
    - schedule: Cron 표현식
    - payload: 실행 시 전달할 입력 데이터 (JSONB)
    - next_run_date: 다음 실행 예정 시간
    - end_time: 스케줄 종료 시간
    """

    __tablename__ = "crons"

    cron_id: Mapped[str] = mapped_column(
        Text, primary_key=True, server_default=text("uuid_generate_v4()::text")
    )
    assistant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("assistant.assistant_id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("thread.thread_id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    schedule: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    next_run_date: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=text("now()"))

    __table_args__ = (
        Index("idx_crons_user_id", "user_id"),
        Index("idx_crons_assistant_id", "assistant_id"),
        Index("idx_crons_thread_id", "thread_id"),
        Index("idx_crons_next_run_date", "next_run_date"),
    )


# ---------------------------------------------------------------------------
# 세션 팩토리 (FastAPI 의존성 주입용)
# ---------------------------------------------------------------------------

async_session_maker: async_sessionmaker[AsyncSession] | None = None


def _get_session_maker() -> async_sessionmaker[AsyncSession]:
    """db_manager 엔진에 바인딩된 async_sessionmaker 반환 (캐시됨)

    이 함수는 AsyncSession 팩토리를 지연 생성하고 캐시합니다.
    FastAPI 의존성에서 사용되며, 각 요청마다 새로운 세션을 생성합니다.

    Returns:
        async_sessionmaker: AsyncSession 팩토리
    """
    global async_session_maker
    if async_session_maker is None:
        from .database import db_manager

        engine = db_manager.get_engine()
        async_session_maker = async_sessionmaker(engine, expire_on_commit=False)
    return async_session_maker


def _extract_rls_context(request: Request) -> tuple[str | None, str | None]:
    """Extract org/user identifiers from the authenticated request context."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None, None

    user_payload = user.to_dict() if hasattr(user, "to_dict") else None
    if isinstance(user_payload, dict):
        return user_payload.get("org_id"), user_payload.get("identity")

    return getattr(user, "org_id", None), getattr(user, "identity", None)


async def _get_session_core(request: Request | None) -> AsyncIterator[AsyncSession]:
    """Core session generator with optional RLS support."""
    maker = _get_session_maker()
    async with maker() as session:
        rls_active = False
        if request is not None:
            org_id, user_id = _extract_rls_context(request)
            if org_id is not None or user_id is not None:
                await set_rls_context(session, org_id=org_id, user_id=user_id)
                rls_active = True
        try:
            yield session
        finally:
            if rls_active:
                await clear_rls_context(session)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 라우터용 데이터베이스 세션 의존성 (RLS 없음)

    이 함수는 FastAPI의 Depends()에서 사용되어 각 요청마다
    새로운 AsyncSession을 생성하고 요청 종료 시 자동으로 정리합니다.

    사용 예:
        @router.get("/assistants")
        async def list_assistants(session: AsyncSession = Depends(get_session)):
            result = await session.execute(select(Assistant))
            return result.scalars().all()

    Yields:
        AsyncSession: 요청별 데이터베이스 세션
    """
    async for session in _get_session_core(None):
        yield session


async def get_session_with_rls(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI 라우터용 데이터베이스 세션 의존성 (RLS 포함)

    이 함수는 요청 컨텍스트에서 org_id/user_id를 추출하여
    Row-Level Security 컨텍스트를 자동으로 설정합니다.

    사용 예:
        @router.get("/secure-data")
        async def get_data(session: AsyncSession = Depends(get_session_with_rls)):
            # RLS가 자동으로 적용됨
            result = await session.execute(select(SecureData))
            return result.scalars().all()

    Yields:
        AsyncSession: RLS 컨텍스트가 설정된 데이터베이스 세션
    """
    async for session in _get_session_core(request):
        yield session
