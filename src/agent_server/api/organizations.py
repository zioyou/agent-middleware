"""Organization API 라우터

이 모듈은 조직(Organization) 기반 멀티테넌시를 위한 API 엔드포인트를 제공합니다.
조직, 멤버십, API 키 관리를 위한 CRUD 엔드포인트가 포함됩니다.

Agent Protocol 확장:
    이 API는 Agent Protocol 표준을 확장하여 멀티테넌시 지원을 추가합니다.
    조직 내 사용자들은 Assistant, Thread, Run 리소스를 공유할 수 있습니다.

주요 엔드포인트:
    조직 관리:
        POST   /organizations                    - 새 조직 생성
        GET    /organizations                    - 사용자 조직 목록 조회
        GET    /organizations/{org_id}           - 조직 상세 조회
        GET    /organizations/slug/{slug}        - slug로 조직 조회
        PATCH  /organizations/{org_id}           - 조직 정보 수정
        DELETE /organizations/{org_id}           - 조직 삭제

    멤버십 관리:
        GET    /organizations/{org_id}/members           - 멤버 목록 조회
        POST   /organizations/{org_id}/members           - 멤버 추가
        PATCH  /organizations/{org_id}/members/{user_id} - 멤버 역할 변경
        DELETE /organizations/{org_id}/members/{user_id} - 멤버 제거

    API 키 관리:
        GET    /organizations/{org_id}/api-keys          - API 키 목록 조회
        POST   /organizations/{org_id}/api-keys          - API 키 생성
        DELETE /organizations/{org_id}/api-keys/{key_id} - API 키 폐기

RBAC (Role-Based Access Control):
    - OWNER:  조직 삭제, owner 역할 부여, 모든 관리 권한
    - ADMIN:  멤버 관리, 설정 변경, API 키 관리
    - MEMBER: 리소스 생성/수정 가능 (조직 관리 불가)
    - VIEWER: 읽기 전용 접근

사용 예:
    # 조직 생성
    POST /organizations
    {"name": "Acme Corp", "description": "AI 팀"}

    # 멤버 추가
    POST /organizations/{org_id}/members
    {"user_id": "user-123", "role": "admin"}

    # API 키 생성
    POST /organizations/{org_id}/api-keys
    {"name": "Production", "scopes": ["assistants:read", "runs:write"]}
"""

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth_deps import get_current_user
from ..models.auth import User
from ..models.organization import (
    APIKeyCreate,
    APIKeyList,
    APIKeyWithSecret,
    Organization,
    OrganizationCreate,
    OrganizationList,
    OrganizationMember,
    OrganizationMemberCreate,
    OrganizationMemberList,
    OrganizationMemberUpdate,
    OrganizationUpdate,
)
from ..services.organization_service import (
    OrganizationService,
    get_organization_service,
)

router = APIRouter(prefix="/organizations", tags=["Organizations"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 조직 CRUD 엔드포인트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.post("", response_model=Organization, status_code=201)
async def create_organization(
    request: OrganizationCreate,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> Organization:
    """새로운 조직 생성

    인증된 사용자가 새로운 조직을 생성합니다.
    생성한 사용자는 자동으로 OWNER 역할을 부여받습니다.

    동작 흐름:
        1. 요청 데이터 검증 (name, slug 등)
        2. slug 생성 (미제공 시 name에서 자동 생성)
        3. slug 중복 확인
        4. 조직 레코드 생성
        5. 생성자를 OWNER로 멤버십 추가

    Args:
        request: 조직 생성 요청 데이터
            - name: 조직 이름 (필수)
            - slug: URL 친화적 식별자 (선택, 자동 생성 가능)
            - description: 조직 설명 (선택)
            - settings: 조직 설정 (선택)
            - metadata: 추가 메타데이터 (선택)
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        Organization: 생성된 조직 정보

    Raises:
        HTTPException(409): slug가 이미 존재하는 경우
    """
    return await service.create_organization(request, user.identity)


@router.get("", response_model=OrganizationList)
async def list_organizations(
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationList:
    """사용자가 속한 조직 목록 조회

    인증된 사용자가 멤버로 속한 모든 조직을 반환합니다.
    역할(OWNER, ADMIN, MEMBER, VIEWER)에 관계없이 모든 소속 조직이 포함됩니다.

    Args:
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        OrganizationList: 조직 목록 및 총 개수
            - organizations: 조직 배열
            - total: 전체 개수
    """
    return await service.list_user_organizations(user.identity)


@router.get("/{org_id}", response_model=Organization)
async def get_organization(
    org_id: str,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> Organization:
    """조직 상세 정보 조회

    org_id로 특정 조직의 상세 정보를 조회합니다.
    사용자가 해당 조직의 멤버인 경우에만 조회 가능합니다.

    Args:
        org_id: 조직 고유 식별자 (UUID)
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        Organization: 조직 상세 정보

    Raises:
        HTTPException(404): 조직이 존재하지 않거나 접근 권한 없음
    """
    org = await service.get_organization(org_id, user.identity)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.get("/slug/{slug}", response_model=Organization)
async def get_organization_by_slug(
    slug: str,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> Organization:
    """slug로 조직 조회

    URL 친화적 slug로 조직을 조회합니다.
    사용자가 해당 조직의 멤버인 경우에만 조회 가능합니다.

    Args:
        slug: URL 친화적 조직 식별자 (예: "acme-corp")
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        Organization: 조직 상세 정보

    Raises:
        HTTPException(404): 조직이 존재하지 않거나 접근 권한 없음
    """
    org = await service.get_organization_by_slug(slug, user.identity)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


@router.patch("/{org_id}", response_model=Organization)
async def update_organization(
    org_id: str,
    request: OrganizationUpdate,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> Organization:
    """조직 정보 수정

    조직의 이름, 설명, 설정, 메타데이터를 수정합니다.
    ADMIN 이상의 역할이 필요합니다.

    PATCH 시맨틱:
        - 제공된 필드만 업데이트
        - None 값은 변경 없음
        - settings/metadata는 얕은 병합 (shallow merge)

    Args:
        org_id: 조직 고유 식별자 (UUID)
        request: 수정할 필드
            - name: 새로운 조직 이름 (선택)
            - description: 새로운 설명 (선택)
            - settings: 병합할 설정 (선택)
            - metadata: 병합할 메타데이터 (선택)
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        Organization: 수정된 조직 정보

    Raises:
        HTTPException(403): 권한 부족 (ADMIN 이상 필요)
        HTTPException(404): 조직이 존재하지 않음
    """
    return await service.update_organization(org_id, request, user.identity)


@router.delete("/{org_id}", status_code=204)
async def delete_organization(
    org_id: str,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> None:
    """조직 삭제

    조직과 모든 관련 데이터(멤버십, API 키)를 삭제합니다.
    OWNER 역할만 삭제할 수 있습니다.

    경고:
        - 이 작업은 되돌릴 수 없습니다
        - 조직에 연결된 Assistant, Thread, Run은 org_id가 NULL로 설정됩니다

    Args:
        org_id: 삭제할 조직 ID
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Raises:
        HTTPException(403): 권한 부족 (OWNER만 가능)
        HTTPException(404): 조직이 존재하지 않음
    """
    await service.delete_organization(org_id, user.identity)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 멤버십 관리 엔드포인트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/{org_id}/members", response_model=OrganizationMemberList)
async def list_members(
    org_id: str,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationMemberList:
    """조직 멤버 목록 조회

    조직에 속한 모든 멤버와 그들의 역할을 반환합니다.
    조직의 모든 멤버가 이 엔드포인트에 접근할 수 있습니다.

    Args:
        org_id: 조직 고유 식별자 (UUID)
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        OrganizationMemberList: 멤버 목록 및 총 인원
            - members: 멤버 배열 (user_id, role, joined_at 포함)
            - total: 전체 멤버 수

    Raises:
        HTTPException(403): 조직 멤버가 아님
        HTTPException(404): 조직이 존재하지 않음
    """
    return await service.list_members(org_id, user.identity)


@router.post("/{org_id}/members", response_model=OrganizationMember, status_code=201)
async def add_member(
    org_id: str,
    request: OrganizationMemberCreate,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationMember:
    """조직에 새 멤버 추가

    기존 사용자를 조직에 초대합니다.
    ADMIN 이상의 역할이 필요하며, OWNER 역할 부여는 OWNER만 가능합니다.

    동작 흐름:
        1. 요청자 권한 확인 (ADMIN 이상)
        2. OWNER 역할 부여 시 요청자가 OWNER인지 확인
        3. 중복 멤버십 확인
        4. 멤버십 레코드 생성

    Args:
        org_id: 조직 고유 식별자 (UUID)
        request: 멤버 추가 요청
            - user_id: 추가할 사용자 ID (필수)
            - role: 부여할 역할 (기본: member)
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        OrganizationMember: 생성된 멤버십 정보

    Raises:
        HTTPException(403): 권한 부족
        HTTPException(404): 조직이 존재하지 않음
        HTTPException(409): 이미 멤버인 사용자
    """
    return await service.add_member(org_id, request, user.identity)


@router.patch("/{org_id}/members/{member_user_id}", response_model=OrganizationMember)
async def update_member_role(
    org_id: str,
    member_user_id: str,
    request: OrganizationMemberUpdate,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationMember:
    """멤버 역할 변경

    조직 멤버의 역할을 변경합니다.
    ADMIN 이상의 역할이 필요하며, OWNER 관련 변경은 OWNER만 가능합니다.

    제약 조건:
        - OWNER → 다른 역할: OWNER만 가능, 최소 1명의 OWNER 유지 필요
        - 다른 역할 → OWNER: OWNER만 가능
        - ADMIN/MEMBER/VIEWER 간 변경: ADMIN 이상 가능

    Args:
        org_id: 조직 고유 식별자 (UUID)
        member_user_id: 역할을 변경할 멤버의 user_id
        request: 역할 변경 요청
            - role: 새로운 역할 (필수)
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        OrganizationMember: 업데이트된 멤버십 정보

    Raises:
        HTTPException(400): 마지막 OWNER를 강등하려는 경우
        HTTPException(403): 권한 부족
        HTTPException(404): 조직 또는 멤버가 존재하지 않음
    """
    return await service.update_member_role(
        org_id=org_id,
        user_id=member_user_id,
        new_role=request.role,
        requester_id=user.identity,
    )


@router.delete("/{org_id}/members/{member_user_id}", status_code=204)
async def remove_member(
    org_id: str,
    member_user_id: str,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> None:
    """멤버 제거

    조직에서 멤버를 제거합니다.
    자기 자신은 언제든 탈퇴 가능하며, 다른 멤버 제거는 ADMIN 이상이 필요합니다.

    제약 조건:
        - 마지막 OWNER는 제거 불가 (조직에 최소 1명의 OWNER 필요)
        - 자기 자신 탈퇴는 역할과 관계없이 가능

    Args:
        org_id: 조직 고유 식별자 (UUID)
        member_user_id: 제거할 멤버의 user_id
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Raises:
        HTTPException(400): 마지막 OWNER를 제거하려는 경우
        HTTPException(403): 권한 부족 (다른 멤버 제거 시 ADMIN 필요)
        HTTPException(404): 조직 또는 멤버가 존재하지 않음
    """
    await service.remove_member(
        org_id=org_id,
        user_id=member_user_id,
        requester_id=user.identity,
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API 키 관리 엔드포인트
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/{org_id}/api-keys", response_model=APIKeyList)
async def list_api_keys(
    org_id: str,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> APIKeyList:
    """조직 API 키 목록 조회

    조직에 속한 모든 API 키를 반환합니다.
    보안을 위해 key_hash는 포함되지 않으며, key_prefix만 표시됩니다.

    Args:
        org_id: 조직 고유 식별자 (UUID)
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        APIKeyList: API 키 목록 및 총 개수
            - api_keys: API 키 배열 (raw_key 제외)
            - total: 전체 키 개수

    Raises:
        HTTPException(403): 권한 부족 (ADMIN 이상 필요)
        HTTPException(404): 조직이 존재하지 않음
    """
    return await service.list_api_keys(org_id, user.identity)


@router.post("/{org_id}/api-keys", response_model=APIKeyWithSecret, status_code=201)
async def create_api_key(
    org_id: str,
    request: APIKeyCreate,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> APIKeyWithSecret:
    """API 키 생성

    조직용 새 API 키를 생성합니다.
    ADMIN 이상의 역할이 필요합니다.

    중요:
        - 반환되는 raw_key는 이 응답에서만 확인 가능합니다
        - 이후 조회 시 key_prefix만 표시됩니다
        - raw_key를 분실하면 새로운 키를 생성해야 합니다

    동작 흐름:
        1. 요청자 권한 확인 (ADMIN 이상)
        2. 고유 API 키 생성 ("olg_" 접두사 + 랜덤 문자열)
        3. SHA-256 해시 생성 후 저장
        4. 만료일 계산 (expires_in_days 기준)

    Args:
        org_id: 조직 고유 식별자 (UUID)
        request: API 키 생성 요청
            - name: API 키 이름 (필수)
            - scopes: 권한 범위 (선택, 빈 리스트 = 전체 권한)
            - expires_in_days: 만료 기간 (선택, None = 무기한)
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Returns:
        APIKeyWithSecret: 생성된 API 키 (raw_key 포함)

    Raises:
        HTTPException(403): 권한 부족 (ADMIN 이상 필요)
        HTTPException(404): 조직이 존재하지 않음
    """
    return await service.create_api_key(
        org_id=org_id,
        name=request.name,
        scopes=request.scopes,
        expires_in_days=request.expires_in_days,
        created_by=user.identity,
    )


@router.delete("/{org_id}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(
    org_id: str,
    key_id: str,
    user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> None:
    """API 키 폐기

    API 키를 폐기하여 더 이상 인증에 사용할 수 없게 만듭니다.
    ADMIN 이상의 역할이 필요합니다.

    동작:
        - 키 레코드는 삭제되지 않고 revoked_at 필드가 설정됩니다
        - 폐기된 키는 인증에 사용할 수 없습니다
        - 감사(audit) 목적으로 레코드가 유지됩니다

    Args:
        org_id: 조직 고유 식별자 (UUID)
        key_id: 폐기할 API 키 ID
        user: 인증된 사용자 (의존성 주입)
        service: OrganizationService (의존성 주입)

    Raises:
        HTTPException(403): 권한 부족 (ADMIN 이상 필요)
        HTTPException(404): 조직 또는 API 키가 존재하지 않음
    """
    await service.revoke_api_key(
        org_id=org_id,
        key_id=key_id,
        requester_id=user.identity,
    )
