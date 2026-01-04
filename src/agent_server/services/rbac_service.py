from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.orm import (
    OrganizationMember,
)
from ..core.orm import (
    RoleDefinition as RoleDefinitionORM,
)
from ..core.orm import (
    UserCustomPermissions as UserCustomPermissionsORM,
)
from ..models.rbac import (
    SYSTEM_ROLES,
    RoleCreate,
    RoleDefinition,
    RoleUpdate,
    UserCustomPermissions,
    UserPermissionGrant,
)
from .permission_service import PermissionService


class RBACService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._permission_service = PermissionService(session)

    async def list_roles(
        self,
        org_id: str,
        include_system: bool = True,
    ) -> list[RoleDefinition]:
        roles: list[RoleDefinition] = []

        if include_system:
            for name, data in SYSTEM_ROLES.items():
                roles.append(
                    RoleDefinition(
                        id=f"system_{name}",
                        org_id=None,
                        name=name,
                        display_name=data["display_name"],
                        description=data["description"],
                        permissions=data["permissions"],
                        is_system=True,
                        priority=data["priority"],
                        created_at=datetime(2020, 1, 1, tzinfo=UTC),
                        updated_at=datetime(2020, 1, 1, tzinfo=UTC),
                    )
                )

        result = await self._session.execute(
            select(RoleDefinitionORM).where(RoleDefinitionORM.org_id == org_id)
        )
        for row in result.scalars().all():
            roles.append(RoleDefinition.model_validate(row))

        return sorted(roles, key=lambda r: (-r.priority, r.name))

    async def get_role(
        self,
        org_id: str,
        role_name: str,
    ) -> RoleDefinition | None:
        if role_name in SYSTEM_ROLES:
            data = SYSTEM_ROLES[role_name]
            return RoleDefinition(
                id=f"system_{role_name}",
                org_id=None,
                name=role_name,
                display_name=data["display_name"],
                description=data["description"],
                permissions=data["permissions"],
                is_system=True,
                priority=data["priority"],
                created_at=datetime(2020, 1, 1, tzinfo=UTC),
                updated_at=datetime(2020, 1, 1, tzinfo=UTC),
            )

        result = await self._session.execute(
            select(RoleDefinitionORM).where(
                RoleDefinitionORM.org_id == org_id,
                RoleDefinitionORM.name == role_name,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return RoleDefinition.model_validate(row)
        return None

    async def create_role(
        self,
        org_id: str,
        request: RoleCreate,
        created_by: str,
    ) -> RoleDefinition:
        if request.name in SYSTEM_ROLES:
            raise HTTPException(
                status_code=409,
                detail=f"Role name '{request.name}' conflicts with system role",
            )

        existing = await self.get_role(org_id, request.name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Role '{request.name}' already exists in organization",
            )

        now = datetime.now(UTC)
        role_orm = RoleDefinitionORM(
            org_id=org_id,
            name=request.name,
            display_name=request.display_name or request.name.replace("_", " ").title(),
            description=request.description,
            permissions=request.permissions,
            is_system=False,
            priority=request.priority,
            created_at=now,
            updated_at=now,
        )

        self._session.add(role_orm)
        await self._session.commit()
        await self._session.refresh(role_orm)

        return RoleDefinition.model_validate(role_orm)

    async def update_role(
        self,
        org_id: str,
        role_name: str,
        request: RoleUpdate,
        updated_by: str,
    ) -> RoleDefinition:
        if role_name in SYSTEM_ROLES:
            raise HTTPException(
                status_code=403,
                detail="System roles cannot be modified",
            )

        result = await self._session.execute(
            select(RoleDefinitionORM).where(
                RoleDefinitionORM.org_id == org_id,
                RoleDefinitionORM.name == role_name,
            )
        )
        role_orm = result.scalar_one_or_none()

        if not role_orm:
            raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")

        if role_orm.is_system:
            raise HTTPException(
                status_code=403,
                detail="System roles cannot be modified",
            )

        if request.display_name is not None:
            role_orm.display_name = request.display_name
        if request.description is not None:
            role_orm.description = request.description
        if request.permissions is not None:
            role_orm.permissions = request.permissions
        if request.priority is not None:
            role_orm.priority = request.priority

        role_orm.updated_at = datetime.now(UTC)

        await self._session.commit()
        await self._session.refresh(role_orm)

        await self._permission_service.invalidate_role_cache(org_id, role_name)

        return RoleDefinition.model_validate(role_orm)

    async def delete_role(
        self,
        org_id: str,
        role_name: str,
    ) -> None:
        if role_name in SYSTEM_ROLES:
            raise HTTPException(
                status_code=403,
                detail="System roles cannot be deleted",
            )

        result = await self._session.execute(
            select(RoleDefinitionORM).where(
                RoleDefinitionORM.org_id == org_id,
                RoleDefinitionORM.name == role_name,
            )
        )
        role_orm = result.scalar_one_or_none()

        if not role_orm:
            raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")

        if role_orm.is_system:
            raise HTTPException(
                status_code=403,
                detail="System roles cannot be deleted",
            )

        members_result = await self._session.execute(
            select(OrganizationMember.user_id).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.role == role_name,
            )
        )
        members_with_role = members_result.scalars().all()

        if members_with_role:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete role '{role_name}': {len(members_with_role)} members assigned",
            )

        await self._session.delete(role_orm)
        await self._session.commit()

        await self._permission_service.invalidate_role_cache(org_id, role_name)

    async def get_user_custom_permissions(
        self,
        org_id: str,
        user_id: str,
    ) -> UserCustomPermissions | None:
        result = await self._session.execute(
            select(UserCustomPermissionsORM).where(
                UserCustomPermissionsORM.org_id == org_id,
                UserCustomPermissionsORM.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return UserCustomPermissions.model_validate(row)
        return None

    async def update_user_permissions(
        self,
        org_id: str,
        user_id: str,
        request: UserPermissionGrant,
        granted_by: str,
    ) -> UserCustomPermissions:
        result = await self._session.execute(
            select(UserCustomPermissionsORM).where(
                UserCustomPermissionsORM.org_id == org_id,
                UserCustomPermissionsORM.user_id == user_id,
            )
        )
        existing = result.scalar_one_or_none()

        now = datetime.now(UTC)

        if existing:
            existing.granted_permissions = request.granted_permissions
            existing.denied_permissions = request.denied_permissions
            existing.granted_by = granted_by
            existing.granted_at = now
            existing.expires_at = request.expires_at
            existing.reason = request.reason

            await self._session.commit()
            await self._session.refresh(existing)
            perms_orm = existing
        else:
            perms_orm = UserCustomPermissionsORM(
                user_id=user_id,
                org_id=org_id,
                granted_permissions=request.granted_permissions,
                denied_permissions=request.denied_permissions,
                granted_by=granted_by,
                granted_at=now,
                expires_at=request.expires_at,
                reason=request.reason,
            )
            self._session.add(perms_orm)
            await self._session.commit()
            await self._session.refresh(perms_orm)

        await self._permission_service.invalidate_user_cache(user_id, org_id)

        return UserCustomPermissions.model_validate(perms_orm)

    async def delete_user_custom_permissions(
        self,
        org_id: str,
        user_id: str,
    ) -> None:
        result = await self._session.execute(
            select(UserCustomPermissionsORM).where(
                UserCustomPermissionsORM.org_id == org_id,
                UserCustomPermissionsORM.user_id == user_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            await self._session.delete(existing)
            await self._session.commit()
            await self._permission_service.invalidate_user_cache(user_id, org_id)

    async def assign_role(
        self,
        org_id: str,
        user_id: str,
        role_name: str,
        assigned_by: str,
    ) -> str:
        role = await self.get_role(org_id, role_name)
        if not role:
            raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")

        result = await self._session.execute(
            select(OrganizationMember).where(
                OrganizationMember.org_id == org_id,
                OrganizationMember.user_id == user_id,
            )
        )
        member = result.scalar_one_or_none()

        if not member:
            raise HTTPException(
                status_code=404,
                detail=f"User '{user_id}' not a member of organization",
            )

        previous_role = member.role
        member.role = role_name

        await self._session.commit()
        await self._permission_service.invalidate_user_cache(user_id, org_id)

        return previous_role


def get_rbac_service(session: AsyncSession) -> RBACService:
    return RBACService(session)
