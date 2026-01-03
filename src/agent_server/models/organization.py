"""Organization 멀티테넌시 Pydantic 모델

이 모듈은 조직(Organization) 기반 멀티테넌시를 위한 Pydantic 모델을 정의합니다.
조직은 사용자들을 그룹화하고, 리소스(Assistant, Thread, Run)에 대한 공유 접근을 제공합니다.

주요 구성 요소:
• OrganizationRole - 멤버 역할 열거형 (owner/admin/member/viewer)
• OrganizationCreate - 조직 생성 요청 모델
• Organization - 조직 엔티티 모델 (ORM 매핑)
• OrganizationUpdate - 조직 업데이트 요청 모델
• OrganizationMemberCreate - 멤버 추가 요청 모델
• OrganizationMember - 멤버십 엔티티 모델
• OrganizationMemberUpdate - 멤버 역할 변경 모델
• APIKeyCreate - API 키 생성 요청 모델
• APIKey - API 키 엔티티 모델 (보안 필드 제외)
• APIKeyWithSecret - 생성 시에만 반환되는 전체 키 포함 모델

사용 예:
    # 조직 생성
    org_create = OrganizationCreate(
        name="Acme Corp",
        slug="acme-corp",  # 선택 - 미제공 시 name에서 자동 생성
        settings={"rate_limit": 1000}
    )

    # 멤버 추가
    member_create = OrganizationMemberCreate(
        user_id="user-123",
        role=OrganizationRole.ADMIN
    )

    # API 키 생성
    api_key_create = APIKeyCreate(
        name="Production API Key",
        scopes=["assistants:read", "runs:write"]
    )
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrganizationRole(str, Enum):
    """조직 멤버 역할

    RBAC(Role-Based Access Control)을 위한 역할 계층:
    - OWNER: 전체 권한, 조직 삭제 가능, 다른 owner 추가 가능
    - ADMIN: 멤버 관리, 설정 변경 가능 (조직 삭제 불가)
    - MEMBER: 리소스 생성/수정 가능 (멤버 관리 불가)
    - VIEWER: 읽기 전용 (생성/수정 불가)
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


# ---------------------------------------------------------------------------
# Organization Models
# ---------------------------------------------------------------------------


class OrganizationCreate(BaseModel):
    """조직 생성 요청 모델

    새로운 조직을 생성할 때 사용하는 요청 모델입니다.
    조직을 생성한 사용자는 자동으로 OWNER 역할을 부여받습니다.

    필드 설명:
        name: 조직 이름 (필수)
            - 표시용 이름 (예: "Acme Corporation")
            - 고유할 필요 없음 (slug가 고유성 보장)
        slug: URL 친화적 식별자 (선택)
            - 영문 소문자, 숫자, 하이픈만 허용
            - 미제공 시 name에서 자동 생성
            - 예: "acme-corp", "my-team-2024"
        description: 조직 설명 (선택)
            - 팀 목적, 프로젝트 설명 등
        settings: 조직 설정 (선택)
            - rate_limit, quotas, features 등 설정
            - 예: {"rate_limit": 1000, "features": ["beta"]}
        metadata: 추가 메타데이터 (선택)
            - 사용자 정의 필드
            - 검색 및 필터링에 활용 가능
    """

    name: str = Field(..., min_length=1, max_length=255, description="조직 이름 (필수)")
    slug: str | None = Field(
        None,
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL 친화적 식별자 (미제공 시 name에서 자동 생성)",
    )
    description: str | None = Field(None, max_length=1000, description="조직 설명")
    settings: dict[str, Any] | None = Field(None, description="조직 설정 (rate_limit, quotas 등)")
    metadata: dict[str, Any] | None = Field(None, description="추가 메타데이터")


class Organization(BaseModel):
    """조직 엔티티 모델

    데이터베이스에 저장된 조직의 전체 정보를 나타내는 모델입니다.
    ORM 모델(Organization)과 직접 매핑되며, API 응답으로 반환됩니다.

    필드 설명:
        org_id: 조직 고유 식별자 (UUID)
        name: 조직 이름
        slug: URL 친화적 식별자 (고유)
        description: 조직 설명 (선택)
        settings: 조직 설정 (JSONB)
        metadata: 추가 메타데이터 (JSONB)
        created_at: 생성 타임스탬프
        updated_at: 최종 수정 타임스탬프

    참고:
        - ORM 모델과 from_attributes=True로 자동 변환
        - slug는 URL에서 조직 식별에 사용 가능
    """

    org_id: str = Field(..., description="조직 고유 식별자 (UUID)")
    name: str = Field(..., description="조직 이름")
    slug: str = Field(..., description="URL 친화적 식별자 (고유)")
    description: str | None = Field(None, description="조직 설명")
    settings: dict[str, Any] = Field(default_factory=dict, description="조직 설정")
    metadata: dict[str, Any] = Field(
        default_factory=dict, alias="metadata_dict", description="추가 메타데이터"
    )
    created_at: datetime = Field(..., description="생성 타임스탬프")
    updated_at: datetime = Field(..., description="최종 수정 타임스탬프")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrganizationUpdate(BaseModel):
    """조직 업데이트 요청 모델

    기존 조직의 정보를 수정할 때 사용합니다.
    PATCH 시맨틱: 제공된 필드만 업데이트, None은 변경 없음

    필드 설명:
        name: 새로운 조직 이름 (선택)
        description: 새로운 설명 (선택)
        settings: 병합할 설정 (선택)
            - 기존 설정에 새 키-값 추가/덮어쓰기
        metadata: 병합할 메타데이터 (선택)
            - 기존 메타데이터에 새 키-값 추가/덮어쓰기

    참고:
        - slug는 업데이트 불가 (고유 식별자이므로)
        - settings/metadata는 얕은 병합 (shallow merge)
    """

    name: str | None = Field(None, min_length=1, max_length=255, description="새로운 조직 이름")
    description: str | None = Field(None, max_length=1000, description="새로운 설명")
    settings: dict[str, Any] | None = Field(None, description="병합할 설정")
    metadata: dict[str, Any] | None = Field(None, description="병합할 메타데이터")


class OrganizationList(BaseModel):
    """조직 목록 응답 모델

    사용자가 속한 조직 목록을 반환합니다.

    필드 설명:
        organizations: 조직 목록
        total: 전체 개수
    """

    organizations: list[Organization] = Field(default_factory=list, description="조직 목록")
    total: int = Field(..., description="전체 조직 개수")


# ---------------------------------------------------------------------------
# Organization Member Models
# ---------------------------------------------------------------------------


class OrganizationMemberCreate(BaseModel):
    """조직 멤버 추가 요청 모델

    기존 사용자를 조직에 초대할 때 사용합니다.

    필드 설명:
        user_id: 추가할 사용자 ID (필수)
        role: 부여할 역할 (기본: member)
            - owner: 전체 권한
            - admin: 멤버/설정 관리
            - member: 리소스 생성/수정
            - viewer: 읽기 전용

    참고:
        - owner 역할 부여는 기존 owner만 가능
        - 이미 멤버인 사용자 추가 시 409 에러
    """

    user_id: str = Field(..., description="추가할 사용자 ID")
    role: OrganizationRole = Field(
        OrganizationRole.MEMBER, description="부여할 역할 (기본: member)"
    )


class OrganizationMember(BaseModel):
    """조직 멤버십 엔티티 모델

    조직과 사용자 간의 멤버십 정보를 나타냅니다.

    필드 설명:
        id: 멤버십 고유 ID
        org_id: 소속 조직 ID
        user_id: 사용자 ID
        role: 현재 역할
        invited_by: 초대한 사용자 ID (선택)
        joined_at: 가입 타임스탬프
    """

    id: str = Field(..., description="멤버십 고유 ID")
    org_id: str = Field(..., description="소속 조직 ID")
    user_id: str = Field(..., description="사용자 ID")
    role: OrganizationRole = Field(..., description="현재 역할")
    invited_by: str | None = Field(None, description="초대한 사용자 ID")
    joined_at: datetime = Field(..., description="가입 타임스탬프")

    model_config = ConfigDict(from_attributes=True)


class OrganizationMemberUpdate(BaseModel):
    """멤버 역할 변경 요청 모델

    조직 멤버의 역할을 변경할 때 사용합니다.

    필드 설명:
        role: 새로운 역할 (필수)

    참고:
        - owner → admin 강등은 최소 1명의 owner가 남아있어야 함
        - owner 역할 부여는 기존 owner만 가능
    """

    role: OrganizationRole = Field(..., description="새로운 역할")


class OrganizationMemberList(BaseModel):
    """조직 멤버 목록 응답 모델

    필드 설명:
        members: 멤버 목록
        total: 전체 멤버 수
    """

    members: list[OrganizationMember] = Field(default_factory=list, description="멤버 목록")
    total: int = Field(..., description="전체 멤버 수")


# ---------------------------------------------------------------------------
# API Key Models
# ---------------------------------------------------------------------------


class APIKeyCreate(BaseModel):
    """API 키 생성 요청 모델

    조직용 API 키를 생성할 때 사용합니다.
    생성 후 반환되는 raw key는 이후 조회 불가하므로 반드시 저장해야 합니다.

    필드 설명:
        name: API 키 이름 (필수)
            - 식별용 이름 (예: "Production Server", "CI/CD Pipeline")
        scopes: 권한 범위 (선택)
            - 허용되는 작업 목록
            - 예: ["assistants:read", "assistants:write", "runs:*"]
            - 빈 리스트면 전체 권한
        expires_in_days: 만료 기간 (선택)
            - 생성일로부터 N일 후 만료
            - None이면 무기한

    참고:
        - 생성된 raw key는 "olg_" 접두사로 시작
        - key_hash만 DB에 저장, raw key는 응답으로만 반환
    """

    name: str = Field(..., min_length=1, max_length=255, description="API 키 이름")
    scopes: list[str] = Field(
        default_factory=list,
        description="권한 범위 (예: ['assistants:read', 'runs:write'])",
    )
    expires_in_days: int | None = Field(
        None, ge=1, le=365, description="만료 기간 (일, 최대 365일)"
    )


class APIKey(BaseModel):
    """API 키 엔티티 모델

    데이터베이스에 저장된 API 키 정보를 나타냅니다.
    보안을 위해 key_hash는 포함되지 않으며, key_prefix만 표시됩니다.

    필드 설명:
        key_id: API 키 고유 ID (UUID)
        org_id: 소속 조직 ID
        name: API 키 이름
        key_prefix: 키 접두사 (예: "olg_abc12...")
            - 식별용으로만 사용, 인증에는 사용 불가
        scopes: 권한 범위
        expires_at: 만료 시간 (선택)
        last_used_at: 마지막 사용 시간 (선택)
        created_by: 생성한 사용자 ID
        created_at: 생성 타임스탬프
        revoked_at: 폐기 시간 (선택)
            - None이 아니면 폐기된 키

    참고:
        - revoked_at이 설정되면 해당 키는 더 이상 인증에 사용 불가
        - last_used_at은 키 사용 시 자동 업데이트
    """

    key_id: str = Field(..., description="API 키 고유 ID")
    org_id: str = Field(..., description="소속 조직 ID")
    name: str = Field(..., description="API 키 이름")
    key_prefix: str = Field(..., description="키 접두사 (식별용)")
    scopes: list[str] = Field(default_factory=list, description="권한 범위")
    expires_at: datetime | None = Field(None, description="만료 시간")
    last_used_at: datetime | None = Field(None, description="마지막 사용 시간")
    created_by: str = Field(..., description="생성한 사용자 ID")
    created_at: datetime = Field(..., description="생성 타임스탬프")
    revoked_at: datetime | None = Field(None, description="폐기 시간 (None이면 활성)")

    model_config = ConfigDict(from_attributes=True)


class APIKeyWithSecret(APIKey):
    """API 키 생성 응답 모델 (raw key 포함)

    API 키 생성 시에만 반환되는 모델입니다.
    raw_key는 이 응답에서만 확인 가능하며, 이후 조회 불가합니다.

    필드 설명:
        raw_key: 실제 API 키 (전체 값)
            - "olg_" 접두사 + 랜덤 문자열
            - 이 값을 Authorization 헤더에 사용
            - 반드시 안전하게 저장할 것

    경고:
        - raw_key는 이 응답에서만 확인 가능
        - 분실 시 새로운 키 생성 필요
    """

    raw_key: str = Field(..., description="실제 API 키 (반드시 저장할 것)")


class APIKeyList(BaseModel):
    """API 키 목록 응답 모델

    필드 설명:
        api_keys: API 키 목록 (raw_key 제외)
        total: 전체 키 개수
    """

    api_keys: list[APIKey] = Field(default_factory=list, description="API 키 목록")
    total: int = Field(..., description="전체 키 개수")
