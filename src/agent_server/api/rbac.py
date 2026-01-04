from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth_deps import get_current_user
from ..core.orm import get_session
from ..core.rbac import RequirePermission, RequireRole
from ..models.auth import User
from ..models.rbac import (
    BulkPermissionCheckRequest,
    BulkPermissionCheckResponse,
    PermissionCheckRequest,
    PermissionCheckResponse,
    RoleAssignment,
    RoleAssignmentResponse,
    RoleCreate,
    RoleDefinition,
    RoleListResponse,
    RoleUpdate,
    UserCustomPermissions,
    UserEffectivePermissions,
    UserPermissionGrant,
)
from ..services.permission_service import PermissionService
from ..services.rbac_service import RBACService

router = APIRouter(prefix="/organizations/{org_id}/rbac", tags=["RBAC"])


@router.get("/roles", response_model=RoleListResponse)
async def list_roles(
    org_id: str,
    include_system: bool = True,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> RoleListResponse:
    service = RBACService(session)
    roles = await service.list_roles(org_id, include_system)
    return RoleListResponse(roles=roles, total=len(roles))


@router.post("/roles", response_model=RoleDefinition, status_code=201)
async def create_role(
    org_id: str,
    request: RoleCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> RoleDefinition:
    service = RBACService(session)
    return await service.create_role(org_id, request, user.identity)


@router.get("/roles/{role_name}", response_model=RoleDefinition)
async def get_role(
    org_id: str,
    role_name: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> RoleDefinition:
    service = RBACService(session)
    role = await service.get_role(org_id, role_name)
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")
    return role


@router.patch("/roles/{role_name}", response_model=RoleDefinition)
async def update_role(
    org_id: str,
    role_name: str,
    request: RoleUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> RoleDefinition:
    service = RBACService(session)
    return await service.update_role(org_id, role_name, request, user.identity)


@router.delete("/roles/{role_name}", status_code=204)
async def delete_role(
    org_id: str,
    role_name: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner")),
) -> None:
    service = RBACService(session)
    await service.delete_role(org_id, role_name)


@router.get("/users/{user_id}/permissions", response_model=UserEffectivePermissions)
async def get_user_permissions(
    org_id: str,
    user_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> UserEffectivePermissions:
    service = PermissionService(session)
    return await service.get_effective_permissions(user_id, org_id)


@router.get("/users/{user_id}/custom-permissions", response_model=UserCustomPermissions | None)
async def get_user_custom_permissions(
    org_id: str,
    user_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> UserCustomPermissions | None:
    service = RBACService(session)
    return await service.get_user_custom_permissions(org_id, user_id)


@router.put("/users/{user_id}/custom-permissions", response_model=UserCustomPermissions)
async def update_user_custom_permissions(
    org_id: str,
    user_id: str,
    request: UserPermissionGrant,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> UserCustomPermissions:
    service = RBACService(session)
    return await service.update_user_permissions(org_id, user_id, request, user.identity)


@router.delete("/users/{user_id}/custom-permissions", status_code=204)
async def delete_user_custom_permissions(
    org_id: str,
    user_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> None:
    service = RBACService(session)
    await service.delete_user_custom_permissions(org_id, user_id)


@router.put("/users/{user_id}/role", response_model=RoleAssignmentResponse)
async def assign_user_role(
    org_id: str,
    user_id: str,
    request: RoleAssignment,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> RoleAssignmentResponse:
    service = RBACService(session)
    previous_role = await service.assign_role(org_id, user_id, request.role, user.identity)
    return RoleAssignmentResponse(
        user_id=user_id,
        org_id=org_id,
        previous_role=previous_role,
        new_role=request.role,
        assigned_by=user.identity,
        assigned_at=datetime.now(UTC),
    )


@router.post("/check", response_model=PermissionCheckResponse)
async def check_permission(
    org_id: str,
    request: PermissionCheckRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> PermissionCheckResponse:
    service = PermissionService(session)
    allowed = await service.check_permission(user.identity, org_id, request.permission)
    return PermissionCheckResponse(
        allowed=allowed,
        permission=request.permission,
        reason="granted" if allowed else "denied",
        checked_at=datetime.now(UTC),
    )


@router.post("/check-bulk", response_model=BulkPermissionCheckResponse)
async def check_permissions_bulk(
    org_id: str,
    request: BulkPermissionCheckRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BulkPermissionCheckResponse:
    service = PermissionService(session)
    results = await service.check_permissions(user.identity, org_id, request.permissions)
    return BulkPermissionCheckResponse(
        results=results,
        all_allowed=all(results.values()),
    )


@router.get("/me/permissions", response_model=UserEffectivePermissions)
async def get_my_permissions(
    org_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserEffectivePermissions:
    service = PermissionService(session)
    return await service.get_effective_permissions(user.identity, org_id)
