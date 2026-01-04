from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache_manager
from ..core.orm import (
    OrganizationMember,
)
from ..core.orm import (
    RoleDefinition as RoleDefinitionORM,
)
from ..core.orm import (
    UserCustomPermissions as UserCustomPermissionsORM,
)
from ..models.rbac import SYSTEM_ROLES, UserEffectivePermissions


class PermissionService:
    CACHE_TTL = 300
    CACHE_PREFIX = "perms"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_effective_permissions(
        self,
        user_id: str,
        org_id: str,
    ) -> UserEffectivePermissions:
        cache_key = f"{self.CACHE_PREFIX}:user:{user_id}:org:{org_id}"
        cached = await cache_manager.get(cache_key)
        if cached:
            return UserEffectivePermissions.model_validate(cached)

        role_name = await self._get_user_role(user_id, org_id)
        role_perms = await self._get_role_permissions(org_id, role_name)
        custom_granted, custom_denied = await self._get_custom_permissions(user_id, org_id)
        effective = self._resolve_permissions(role_perms, custom_granted, custom_denied)

        result = UserEffectivePermissions(
            user_id=user_id,
            org_id=org_id,
            role=role_name,
            role_permissions=role_perms,
            custom_granted=custom_granted,
            custom_denied=custom_denied,
            effective_permissions=effective,
            resolved_at=datetime.now(UTC),
        )

        await cache_manager.set(cache_key, result.model_dump(mode="json"), ttl=self.CACHE_TTL)

        return result

    async def check_permission(
        self,
        user_id: str,
        org_id: str,
        required_permission: str,
    ) -> bool:
        effective = await self.get_effective_permissions(user_id, org_id)
        return self._matches_permission(required_permission, effective.effective_permissions)

    async def check_permissions(
        self,
        user_id: str,
        org_id: str,
        required_permissions: list[str],
    ) -> dict[str, bool]:
        effective = await self.get_effective_permissions(user_id, org_id)
        return {
            perm: self._matches_permission(perm, effective.effective_permissions)
            for perm in required_permissions
        }

    async def _get_user_role(self, user_id: str, org_id: str) -> str:
        result = await self._session.execute(
            select(OrganizationMember.role)
            .where(OrganizationMember.org_id == org_id)
            .where(OrganizationMember.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        return row if row else "viewer"

    async def _get_role_permissions(self, org_id: str, role_name: str) -> list[str]:
        if role_name in SYSTEM_ROLES:
            return list(SYSTEM_ROLES[role_name]["permissions"])

        result = await self._session.execute(
            select(RoleDefinitionORM.permissions).where(
                (RoleDefinitionORM.org_id == org_id) | (RoleDefinitionORM.org_id.is_(None)),
                RoleDefinitionORM.name == role_name,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return list(row)

        return list(SYSTEM_ROLES.get("viewer", {}).get("permissions", []))

    async def _get_custom_permissions(self, user_id: str, org_id: str) -> tuple[list[str], list[str]]:
        now = datetime.now(UTC)
        result = await self._session.execute(
            select(UserCustomPermissionsORM).where(
                UserCustomPermissionsORM.user_id == user_id,
                UserCustomPermissionsORM.org_id == org_id,
            )
        )
        row = result.scalar_one_or_none()

        if row is None:
            return [], []

        if row.expires_at and row.expires_at <= now:
            return [], []

        return list(row.granted_permissions or []), list(row.denied_permissions or [])

    def _matches_permission(self, required: str, granted: list[str]) -> bool:
        for perm in granted:
            if perm == "*":
                return True
            if perm == required:
                return True
            if perm.endswith(":*"):
                prefix = perm[:-1]
                if required.startswith(prefix):
                    return True
        return False

    def _resolve_permissions(
        self,
        role_perms: list[str],
        custom_granted: list[str],
        custom_denied: list[str],
    ) -> list[str]:
        all_perms = set(role_perms) | set(custom_granted)

        for denied in custom_denied:
            if denied == "*":
                return []

            all_perms.discard(denied)

            if denied.endswith(":*"):
                prefix = denied[:-1]
                all_perms = {p for p in all_perms if not p.startswith(prefix)}

        return sorted(all_perms)

    async def invalidate_user_cache(self, user_id: str, org_id: str) -> None:
        cache_key = f"{self.CACHE_PREFIX}:user:{user_id}:org:{org_id}"
        await cache_manager.delete(cache_key)

    async def invalidate_role_cache(self, org_id: str, role_name: str) -> None:
        result = await self._session.execute(
            select(OrganizationMember.user_id)
            .where(OrganizationMember.org_id == org_id)
            .where(OrganizationMember.role == role_name)
        )
        user_ids = [row[0] for row in result.all()]

        for uid in user_ids:
            await self.invalidate_user_cache(uid, org_id)

    async def invalidate_org_cache(self, org_id: str) -> None:
        await cache_manager.delete_pattern(f"{self.CACHE_PREFIX}:user:*:org:{org_id}")


def get_permission_service(session: AsyncSession) -> PermissionService:
    return PermissionService(session)
