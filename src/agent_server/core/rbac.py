from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .auth_deps import get_current_user
from .orm import OrganizationMember, get_session


async def _get_user_org_id(request: Request) -> str | None:
    user = getattr(request.state, "user", None)
    if user and hasattr(user, "org_id"):
        return user.org_id
    return None


async def _get_user_role_in_org(
    session: AsyncSession,
    user_id: str,
    org_id: str,
) -> str | None:
    from sqlalchemy import select

    result = await session.execute(
        select(OrganizationMember.role).where(
            OrganizationMember.org_id == org_id,
            OrganizationMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


class RequirePermission:
    def __init__(self, *permissions: str) -> None:
        self._permissions = permissions

    async def __call__(
        self,
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> bool:
        from ..services.permission_service import PermissionService

        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")

        org_id = getattr(user, "org_id", None)
        if not org_id:
            raise HTTPException(status_code=400, detail="Organization context required")

        perm_service = PermissionService(session)

        for perm in self._permissions:
            if await perm_service.check_permission(user.identity, org_id, perm):
                return True

        raise HTTPException(
            status_code=403,
            detail=f"Permission denied. Required: {', '.join(self._permissions)}",
        )


class RequireRole:
    def __init__(self, *roles: str) -> None:
        self._roles = roles

    async def __call__(
        self,
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> str:
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required")

        org_id = getattr(user, "org_id", None)
        if not org_id:
            raise HTTPException(status_code=400, detail="Organization context required")

        user_role = await _get_user_role_in_org(session, user.identity, org_id)

        if user_role is None:
            raise HTTPException(status_code=403, detail="Not a member of organization")

        if user_role not in self._roles:
            raise HTTPException(
                status_code=403,
                detail=f"Role required: {', '.join(self._roles)}. Your role: {user_role}",
            )

        return user_role


def require_permission(*permissions: str) -> Callable[..., Any]:
    checker = RequirePermission(*permissions)
    return Depends(checker)


def require_role(*roles: str) -> Callable[..., Any]:
    checker = RequireRole(*roles)
    return Depends(checker)


async def check_permission_async(
    session: AsyncSession,
    user_id: str,
    org_id: str,
    permission: str,
) -> bool:
    from ..services.permission_service import PermissionService

    perm_service = PermissionService(session)
    return await perm_service.check_permission(user_id, org_id, permission)


async def get_user_permissions_async(
    session: AsyncSession,
    user_id: str,
    org_id: str,
) -> list[str]:
    from ..services.permission_service import PermissionService

    perm_service = PermissionService(session)
    result = await perm_service.get_effective_permissions(user_id, org_id)
    return result.effective_permissions
