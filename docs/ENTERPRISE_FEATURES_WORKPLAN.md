# Enterprise Features Work Plan

> **작성일:** 2026년 1월 5일
> **버전:** 1.0.0
> **범위:** RBAC, S3 Storage, Advanced Rate Limiting

---

## Executive Summary

이 문서는 Open LangGraph Platform의 3가지 엔터프라이즈 기능에 대한 심도 깊은 구현 계획을 제공합니다:

| Feature | Priority | Effort | Key Deliverables |
|---------|----------|--------|------------------|
| **RBAC** | P1 | ~45 hours | Fine-grained permissions, decorators, caching |
| **S3 Storage** | P2 | ~40 hours | StorageService, presigned URLs, multi-tenant |
| **Rate Limiting Advanced** | P1 | ~35 hours | DB-controlled rules, sliding window, analytics |

**총 예상 소요 시간:** ~120 hours (3-4 weeks)

---

## Table of Contents

1. [Feature 1: RBAC (Role-Based Access Control)](#feature-1-rbac)
2. [Feature 2: S3 Compatible Storage](#feature-2-s3-storage)
3. [Feature 3: Advanced Rate Limiting](#feature-3-rate-limiting)
4. [Implementation Schedule](#implementation-schedule)
5. [Risk Mitigation](#risk-mitigation)

---

## Feature 1: RBAC

### 1.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Request Flow                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  HTTP Request → Auth Middleware → Permission Check → Route Handler       │
│       │              │                  │                                │
│       ▼              ▼                  ▼                                │
│  ┌─────────┐    ┌─────────┐      ┌──────────────┐                       │
│  │ Headers │    │ User    │      │ Permission   │                       │
│  │ (JWT)   │    │ Context │      │ Service      │                       │
│  └─────────┘    └─────────┘      └──────┬───────┘                       │
│                                         │                                │
│                 ┌───────────────────────┼───────────────────────┐       │
│                 │                       ▼                       │       │
│                 │              ┌──────────────┐                 │       │
│                 │              │ Redis Cache  │◄────┐           │       │
│                 │              │ (5 min TTL)  │     │           │       │
│                 │              └──────┬───────┘     │           │       │
│                 │                     │             │           │       │
│                 │                     ▼             │           │       │
│                 │   Cache Miss ┌──────────────┐    │ Cache     │       │
│                 │   ─────────►│ PostgreSQL   │────┘ Set       │       │
│                 │              │              │                 │       │
│                 │              │ role_defs    │                 │       │
│                 │              │ user_perms   │                 │       │
│                 │              │ org_members  │                 │       │
│                 │              └──────────────┘                 │       │
│                 │                                               │       │
│                 └───────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Permission String Format

```
{resource}:{action}

Examples:
- assistants:read
- assistants:write
- assistants:delete
- assistants:*        (wildcard - all actions)
- threads:read
- threads:write
- runs:create
- runs:cancel
- store:read
- store:write
- crons:*
- organization:read
- organization:manage_members
- organization:manage_roles
- audit:read
- audit:export
- quotas:read
- quotas:update
```

### 1.3 Database Schema

#### Role Definitions Table

```sql
-- alembic/versions/20260105_add_rbac_tables.py

CREATE TABLE role_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id TEXT REFERENCES organizations(org_id) ON DELETE CASCADE,
    name VARCHAR(64) NOT NULL,
    display_name VARCHAR(128),
    description TEXT,
    permissions TEXT[] NOT NULL DEFAULT '{}',  -- Array of permission strings
    is_system BOOLEAN DEFAULT FALSE,           -- System roles can't be deleted
    priority INTEGER DEFAULT 0,                -- Higher = more permissions
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT uq_role_org_name UNIQUE (org_id, name)
);

CREATE INDEX idx_role_definitions_org_id ON role_definitions(org_id);
CREATE INDEX idx_role_definitions_name ON role_definitions(name);

-- User custom permissions (overrides beyond role)
CREATE TABLE user_custom_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    org_id TEXT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    granted_permissions TEXT[] DEFAULT '{}',   -- Additional permissions
    denied_permissions TEXT[] DEFAULT '{}',    -- Explicit denials (override grants)
    granted_by TEXT,
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ,                    -- Optional expiration
    reason TEXT,
    
    CONSTRAINT uq_user_org_custom_perms UNIQUE (user_id, org_id)
);

CREATE INDEX idx_user_custom_perms_user_org ON user_custom_permissions(user_id, org_id);
```

#### Default System Roles (Seed Data)

```python
# src/agent_server/services/rbac_service.py

SYSTEM_ROLES = {
    "owner": {
        "display_name": "Owner",
        "description": "Full access to all resources and organization management",
        "permissions": ["*"],  # Wildcard = all permissions
        "priority": 100,
    },
    "admin": {
        "display_name": "Administrator",
        "description": "Manage members, settings, and all resources",
        "permissions": [
            "assistants:*", "threads:*", "runs:*", "store:*", "crons:*",
            "organization:read", "organization:manage_members",
            "audit:read", "audit:export", "quotas:read", "quotas:update",
        ],
        "priority": 80,
    },
    "developer": {
        "display_name": "Developer",
        "description": "Create and manage AI agents and workflows",
        "permissions": [
            "assistants:*", "threads:*", "runs:*", "store:read", "store:write",
            "crons:*", "organization:read", "quotas:read",
        ],
        "priority": 60,
    },
    "viewer": {
        "display_name": "Viewer",
        "description": "Read-only access to resources",
        "permissions": [
            "assistants:read", "threads:read", "runs:read", "store:read",
            "crons:read", "organization:read", "quotas:read",
        ],
        "priority": 20,
    },
    "api_user": {
        "display_name": "API User",
        "description": "Limited API access for automated systems",
        "permissions": [
            "assistants:read", "threads:read", "threads:write",
            "runs:read", "runs:create", "store:read", "store:write",
        ],
        "priority": 40,
    },
}
```

### 1.4 Pydantic Models

```python
# src/agent_server/models/rbac.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

class Permission(str, Enum):
    """Fine-grained permissions"""
    # Assistants
    ASSISTANTS_READ = "assistants:read"
    ASSISTANTS_WRITE = "assistants:write"
    ASSISTANTS_DELETE = "assistants:delete"
    ASSISTANTS_ALL = "assistants:*"
    
    # Threads
    THREADS_READ = "threads:read"
    THREADS_WRITE = "threads:write"
    THREADS_DELETE = "threads:delete"
    THREADS_ALL = "threads:*"
    
    # Runs
    RUNS_READ = "runs:read"
    RUNS_CREATE = "runs:create"
    RUNS_CANCEL = "runs:cancel"
    RUNS_DELETE = "runs:delete"
    RUNS_ALL = "runs:*"
    
    # Store
    STORE_READ = "store:read"
    STORE_WRITE = "store:write"
    STORE_DELETE = "store:delete"
    STORE_ALL = "store:*"
    
    # Crons
    CRONS_READ = "crons:read"
    CRONS_WRITE = "crons:write"
    CRONS_DELETE = "crons:delete"
    CRONS_ALL = "crons:*"
    
    # Organization
    ORG_READ = "organization:read"
    ORG_UPDATE = "organization:update"
    ORG_MANAGE_MEMBERS = "organization:manage_members"
    ORG_MANAGE_ROLES = "organization:manage_roles"
    ORG_DELETE = "organization:delete"
    
    # Audit
    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"
    
    # Quotas
    QUOTAS_READ = "quotas:read"
    QUOTAS_UPDATE = "quotas:update"
    
    # Wildcard
    ALL = "*"


class RoleDefinition(BaseModel):
    """Role definition with permissions"""
    id: str
    org_id: str | None = None
    name: str
    display_name: str | None = None
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)
    is_system: bool = False
    priority: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RoleCreate(BaseModel):
    """Create a custom role"""
    name: str = Field(..., min_length=1, max_length=64, pattern=r'^[a-z_][a-z0-9_]*$')
    display_name: str | None = None
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=99)


class RoleUpdate(BaseModel):
    """Update a role"""
    display_name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None
    priority: int | None = Field(default=None, ge=0, le=99)


class UserPermissionGrant(BaseModel):
    """Grant/deny custom permissions to a user"""
    granted_permissions: list[str] = Field(default_factory=list)
    denied_permissions: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    reason: str | None = None


class UserEffectivePermissions(BaseModel):
    """User's effective permissions after resolution"""
    user_id: str
    org_id: str
    role: str
    role_permissions: list[str]
    custom_granted: list[str]
    custom_denied: list[str]
    effective_permissions: list[str]
    resolved_at: datetime


class PermissionCheckRequest(BaseModel):
    """Request to check a specific permission"""
    permission: str
    resource_id: str | None = None


class PermissionCheckResponse(BaseModel):
    """Result of permission check"""
    allowed: bool
    permission: str
    reason: str | None = None
```

### 1.5 Service Layer

```python
# src/agent_server/services/permission_service.py

from typing import Optional
import fnmatch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache_manager
from ..core.orm import RoleDefinition as RoleORM, UserCustomPermissions as UserPermsORM
from ..models.rbac import UserEffectivePermissions

class PermissionService:
    """Permission resolution and caching service"""
    
    CACHE_TTL = 300  # 5 minutes
    CACHE_PREFIX = "perms"
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_effective_permissions(
        self,
        user_id: str,
        org_id: str,
    ) -> UserEffectivePermissions:
        """
        Get user's effective permissions with caching.
        
        Resolution order:
        1. Get role from organization_members
        2. Get role permissions from role_definitions
        3. Get custom permissions from user_custom_permissions
        4. Apply denials (denied_permissions override everything)
        5. Expand wildcards
        """
        # Check cache
        cache_key = f"{self.CACHE_PREFIX}:user:{user_id}:org:{org_id}"
        cached = await cache_manager.get(cache_key)
        if cached:
            return UserEffectivePermissions.model_validate(cached)
        
        # Get user's role in organization
        role_name = await self._get_user_role(user_id, org_id)
        
        # Get role permissions
        role_perms = await self._get_role_permissions(org_id, role_name)
        
        # Get custom permissions
        custom_granted, custom_denied = await self._get_custom_permissions(user_id, org_id)
        
        # Resolve effective permissions
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
        
        # Cache result
        await cache_manager.set(cache_key, result.model_dump(), ttl=self.CACHE_TTL)
        
        return result
    
    async def check_permission(
        self,
        user_id: str,
        org_id: str,
        required_permission: str,
    ) -> bool:
        """Check if user has a specific permission."""
        effective = await self.get_effective_permissions(user_id, org_id)
        return self._matches_permission(required_permission, effective.effective_permissions)
    
    def _matches_permission(self, required: str, granted: list[str]) -> bool:
        """Check if required permission matches any granted permission."""
        for perm in granted:
            if perm == "*":
                return True
            if perm == required:
                return True
            # Wildcard matching: "assistants:*" matches "assistants:read"
            if perm.endswith(":*"):
                prefix = perm[:-1]  # "assistants:"
                if required.startswith(prefix):
                    return True
        return False
    
    def _resolve_permissions(
        self,
        role_perms: list[str],
        custom_granted: list[str],
        custom_denied: list[str],
    ) -> list[str]:
        """Resolve effective permissions with denial handling."""
        # Start with role permissions + custom grants
        all_perms = set(role_perms) | set(custom_granted)
        
        # Remove denied permissions
        for denied in custom_denied:
            if denied == "*":
                return []  # Deny all
            
            # Exact match removal
            all_perms.discard(denied)
            
            # Wildcard denial: "assistants:*" denies all assistants:* permissions
            if denied.endswith(":*"):
                prefix = denied[:-1]
                all_perms = {p for p in all_perms if not p.startswith(prefix)}
        
        return sorted(all_perms)
    
    async def invalidate_user_cache(self, user_id: str, org_id: str) -> None:
        """Invalidate user's permission cache."""
        cache_key = f"{self.CACHE_PREFIX}:user:{user_id}:org:{org_id}"
        await cache_manager.delete(cache_key)
    
    async def invalidate_role_cache(self, org_id: str, role_name: str) -> None:
        """Invalidate cache for all users with a role."""
        # Get all users with this role
        from ..core.orm import OrganizationMember
        
        result = await self.session.execute(
            select(OrganizationMember.user_id)
            .where(OrganizationMember.org_id == org_id)
            .where(OrganizationMember.role == role_name)
        )
        user_ids = [row[0] for row in result.all()]
        
        # Invalidate each user's cache
        for user_id in user_ids:
            await self.invalidate_user_cache(user_id, org_id)
```

### 1.6 Permission Check Decorators

```python
# src/agent_server/core/rbac.py

from functools import wraps
from typing import Callable
from fastapi import Request, HTTPException, Depends

from ..services.permission_service import PermissionService
from .auth_deps import get_current_user

def require_permission(*permissions: str):
    """
    Decorator to require specific permissions.
    
    Usage:
        @router.delete("/assistants/{assistant_id}")
        @require_permission("assistants:delete")
        async def delete_assistant(...):
            ...
    
    Multiple permissions (OR logic):
        @require_permission("assistants:write", "assistants:delete")
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            # Extract request from args or kwargs
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request is None:
                raise HTTPException(500, "Request object not found")
            
            user = getattr(request.state, "user", None)
            if not user:
                raise HTTPException(401, "Authentication required")
            
            # Get permission service
            from ..services.permission_service import get_permission_service
            perm_service = await get_permission_service(request)
            
            # Check if user has ANY of the required permissions
            for perm in permissions:
                if await perm_service.check_permission(
                    user.identity, user.org_id, perm
                ):
                    return await func(*args, request=request, **kwargs)
            
            # No matching permission found
            raise HTTPException(
                403,
                f"Permission denied. Required: {', '.join(permissions)}"
            )
        
        return wrapper
    return decorator


def require_role(*roles: str):
    """
    Decorator to require specific roles.
    
    Usage:
        @router.post("/organizations/{org_id}/roles")
        @require_role("owner", "admin")
        async def create_role(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, request: Request = None, **kwargs):
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            
            if request is None:
                raise HTTPException(500, "Request object not found")
            
            user = getattr(request.state, "user", None)
            if not user:
                raise HTTPException(401, "Authentication required")
            
            # Get user's role in organization
            from ..services.organization_service import get_organization_service
            org_service = await get_organization_service(request)
            
            user_role = await org_service.get_member_role(user.org_id, user.identity)
            
            if user_role not in roles:
                raise HTTPException(
                    403,
                    f"Role required: {', '.join(roles)}. Your role: {user_role}"
                )
            
            return await func(*args, request=request, **kwargs)
        
        return wrapper
    return decorator
```

### 1.7 API Endpoints

```python
# src/agent_server/api/rbac.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.orm import get_session
from ..core.auth_deps import get_current_user
from ..core.rbac import require_permission, require_role
from ..models.auth import User
from ..models.rbac import (
    RoleDefinition, RoleCreate, RoleUpdate,
    UserPermissionGrant, UserEffectivePermissions,
    PermissionCheckRequest, PermissionCheckResponse,
)
from ..services.rbac_service import RBACService

router = APIRouter(prefix="/organizations/{org_id}/rbac", tags=["RBAC"])

# ==================== Role Management ====================

@router.get("/roles", response_model=list[RoleDefinition])
@require_permission("organization:read")
async def list_roles(
    org_id: str,
    include_system: bool = True,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List all roles in organization (system + custom)"""
    service = RBACService(session)
    return await service.list_roles(org_id, include_system)


@router.post("/roles", response_model=RoleDefinition, status_code=201)
@require_role("owner", "admin")
async def create_role(
    org_id: str,
    request: RoleCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a custom role"""
    service = RBACService(session)
    return await service.create_role(org_id, request, user.identity)


@router.get("/roles/{role_name}", response_model=RoleDefinition)
@require_permission("organization:read")
async def get_role(
    org_id: str,
    role_name: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get role details"""
    service = RBACService(session)
    role = await service.get_role(org_id, role_name)
    if not role:
        raise HTTPException(404, f"Role '{role_name}' not found")
    return role


@router.patch("/roles/{role_name}", response_model=RoleDefinition)
@require_role("owner", "admin")
async def update_role(
    org_id: str,
    role_name: str,
    request: RoleUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update a custom role (system roles cannot be modified)"""
    service = RBACService(session)
    return await service.update_role(org_id, role_name, request, user.identity)


@router.delete("/roles/{role_name}", status_code=204)
@require_role("owner")
async def delete_role(
    org_id: str,
    role_name: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a custom role (system roles cannot be deleted)"""
    service = RBACService(session)
    await service.delete_role(org_id, role_name)


# ==================== User Permissions ====================

@router.get("/users/{user_id}/permissions", response_model=UserEffectivePermissions)
@require_permission("organization:read")
async def get_user_permissions(
    org_id: str,
    user_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get user's effective permissions"""
    from ..services.permission_service import PermissionService
    service = PermissionService(session)
    return await service.get_effective_permissions(user_id, org_id)


@router.put("/users/{user_id}/permissions")
@require_role("owner", "admin")
async def update_user_permissions(
    org_id: str,
    user_id: str,
    request: UserPermissionGrant,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Grant or deny custom permissions to a user"""
    service = RBACService(session)
    return await service.update_user_permissions(
        org_id, user_id, request, user.identity
    )


# ==================== Permission Check ====================

@router.post("/check", response_model=PermissionCheckResponse)
async def check_permission(
    org_id: str,
    request: PermissionCheckRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Check if current user has a specific permission"""
    from ..services.permission_service import PermissionService
    service = PermissionService(session)
    
    allowed = await service.check_permission(
        user.identity, org_id, request.permission
    )
    
    return PermissionCheckResponse(
        allowed=allowed,
        permission=request.permission,
        reason="Permission granted" if allowed else "Permission denied",
    )
```

### 1.8 Implementation Tasks

| ID | Task | Priority | Effort | Dependencies | Files |
|----|------|----------|--------|--------------|-------|
| RBAC-001 | Create Pydantic models | P0 | 2h | - | `models/rbac.py` |
| RBAC-002 | Create ORM models | P0 | 2h | RBAC-001 | `core/orm.py` |
| RBAC-003 | Create Alembic migration | P0 | 1h | RBAC-002 | `alembic/versions/` |
| RBAC-004 | Implement PermissionService | P0 | 4h | RBAC-002 | `services/permission_service.py` |
| RBAC-005 | Implement RBACService | P0 | 4h | RBAC-004 | `services/rbac_service.py` |
| RBAC-006 | Create decorators | P0 | 3h | RBAC-004 | `core/rbac.py` |
| RBAC-007 | Create API endpoints | P0 | 4h | RBAC-005, RBAC-006 | `api/rbac.py` |
| RBAC-008 | Seed system roles | P1 | 2h | RBAC-003 | `services/rbac_service.py` |
| RBAC-009 | Add Redis caching | P1 | 3h | RBAC-004 | `services/permission_service.py` |
| RBAC-010 | Cache invalidation | P1 | 2h | RBAC-009 | `services/permission_service.py` |
| RBAC-011 | Update existing endpoints | P1 | 6h | RBAC-006 | `api/*.py` |
| RBAC-012 | Unit tests | P0 | 4h | RBAC-005 | `tests/unit/test_services/` |
| RBAC-013 | Integration tests | P1 | 4h | RBAC-007 | `tests/integration/test_api/` |
| RBAC-014 | E2E tests | P2 | 3h | RBAC-013 | `tests/e2e/` |
| RBAC-015 | Documentation | P2 | 2h | All | `docs/rbac.md` |

**Total: ~45 hours**

---

## Feature 2: S3 Storage

### 2.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Storage Architecture                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Client                                                                  │
│    │                                                                     │
│    ├─► POST /storage/upload-url                                         │
│    │        │                                                            │
│    │        ▼                                                            │
│    │   ┌──────────────┐    ┌──────────────┐                             │
│    │   │ FastAPI      │───►│ StorageService│                            │
│    │   │ Endpoint     │    └──────┬───────┘                             │
│    │   └──────────────┘           │                                     │
│    │                              ▼                                      │
│    │                    ┌───────────────────┐                           │
│    │                    │ S3StorageProvider │                           │
│    │                    │ (aiobotocore)     │                           │
│    │                    └────────┬──────────┘                           │
│    │                             │                                       │
│    │   ┌─────────────────────────┼─────────────────────────┐           │
│    │   │                         ▼                         │           │
│    │   │  ┌──────────────────────────────────────┐        │           │
│    │   │  │           S3 / MinIO                 │        │           │
│    │   │  │                                      │        │           │
│    │   │  │  Bucket: langgraph-files             │        │           │
│    │   │  │  ├── tenants/                        │        │           │
│    │   │  │  │   ├── org-123/                    │        │           │
│    │   │  │  │   │   ├── files/                  │        │           │
│    │   │  │  │   │   │   └── 2026/01/05/        │        │           │
│    │   │  │  │   │   │       └── {file_id}/     │        │           │
│    │   │  │  │   │   │           └── doc.pdf    │        │           │
│    │   │  │  │   │   └── avatars/               │        │           │
│    │   │  │  │   └── org-456/                    │        │           │
│    │   │  └──────────────────────────────────────┘        │           │
│    │   │                                                   │           │
│    │   └───────────────────────────────────────────────────┘           │
│    │                                                                     │
│    │   Returns: {presigned_url, fields}                                 │
│    │                                                                     │
│    └─► Direct Upload to S3 (presigned POST)                             │
│            │                                                             │
│            ▼                                                             │
│        POST /storage/upload-complete                                     │
│            │                                                             │
│            ▼                                                             │
│   ┌──────────────┐    ┌──────────────┐                                  │
│   │ PostgreSQL   │◄───│ StorageService│                                 │
│   │              │    │ (metadata)    │                                  │
│   │ storage_files│    └──────────────┘                                  │
│   └──────────────┘                                                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Database Schema

```sql
-- alembic/versions/20260105_add_storage_files.py

CREATE TABLE storage_files (
    file_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id TEXT NOT NULL REFERENCES organizations(org_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    
    -- S3 Reference
    s3_bucket TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    s3_region TEXT DEFAULT 'us-east-1',
    
    -- File Metadata
    filename TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    
    -- Integrity
    md5_hash TEXT,
    sha256_hash TEXT,
    
    -- Organization
    tags TEXT[] DEFAULT '{}',
    metadata_json JSONB DEFAULT '{}',
    
    -- Lifecycle
    status TEXT DEFAULT 'pending',  -- pending, uploaded, deleted
    uploaded_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,         -- Auto-delete after this time
    deleted_at TIMESTAMPTZ,         -- Soft delete timestamp
    
    -- Audit
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT uq_storage_s3_key UNIQUE (s3_bucket, s3_key)
);

CREATE INDEX idx_storage_files_org_id ON storage_files(org_id);
CREATE INDEX idx_storage_files_user_id ON storage_files(user_id);
CREATE INDEX idx_storage_files_status ON storage_files(status);
CREATE INDEX idx_storage_files_created_at ON storage_files(created_at);
CREATE INDEX idx_storage_files_expires_at ON storage_files(expires_at) 
    WHERE expires_at IS NOT NULL;
CREATE INDEX idx_storage_files_tags ON storage_files USING GIN(tags);
```

### 2.3 Pydantic Models

```python
# src/agent_server/models/storage.py

from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime

class StorageFileCreate(BaseModel):
    """Request to create a file upload"""
    filename: str = Field(..., max_length=255)
    content_type: str = Field(default="application/octet-stream")
    size_bytes: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    expires_in_hours: int | None = Field(default=None, ge=1, le=8760)  # Max 1 year


class StorageFile(BaseModel):
    """Storage file record"""
    file_id: str
    org_id: str
    user_id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    tags: list[str]
    metadata: dict[str, Any]
    uploaded_at: datetime | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PresignedUploadResponse(BaseModel):
    """Response with presigned URL for upload"""
    file_id: str
    upload_url: str
    fields: dict[str, str]  # Form fields for POST
    expires_in: int  # Seconds until URL expires
    s3_key: str


class PresignedDownloadResponse(BaseModel):
    """Response with presigned URL for download"""
    download_url: str
    expires_in: int
    filename: str
    content_type: str
    size_bytes: int


class StorageFileUpdate(BaseModel):
    """Update file metadata"""
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    expires_in_hours: int | None = Field(default=None, ge=1, le=8760)


class StorageListRequest(BaseModel):
    """Request to list files"""
    tags: list[str] | None = None
    status: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class StorageListResponse(BaseModel):
    """Paginated file list"""
    files: list[StorageFile]
    total: int
    limit: int
    offset: int


class StorageQuota(BaseModel):
    """Organization storage quota"""
    org_id: str
    used_bytes: int
    max_bytes: int
    file_count: int
    max_files: int
```

### 2.4 Service Layer

```python
# src/agent_server/services/storage_service.py

from aiobotocore.session import get_session
from botocore.config import Config
from typing import Optional, AsyncGenerator
import hashlib
import uuid
from datetime import datetime, timedelta, UTC

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.orm import StorageFile as StorageFileORM
from ..models.storage import (
    StorageFile, StorageFileCreate, StorageListRequest,
    PresignedUploadResponse, PresignedDownloadResponse, StorageQuota,
)


class S3StorageProvider:
    """S3/MinIO storage provider using aiobotocore"""
    
    def __init__(
        self,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
        bucket: str = "langgraph-files",
    ):
        self.session = get_session()
        self.endpoint_url = endpoint_url
        self.bucket = bucket
        self.credentials = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
        } if access_key and secret_key else {}
        
        self.config = Config(
            signature_version='s3v4',
            region_name=region,
            s3={'addressing_style': 'path'} if endpoint_url else {},
            max_pool_connections=50,
            retries={'max_attempts': 3, 'mode': 'adaptive'},
        )
    
    async def generate_presigned_upload(
        self,
        key: str,
        content_type: str,
        expires_in: int = 3600,
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """Generate presigned POST URL for direct upload"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            config=self.config,
            **self.credentials,
        ) as client:
            conditions = [
                {'bucket': self.bucket},
                ['starts-with', '$key', key],
                {'Content-Type': content_type},
            ]
            
            fields = {
                'key': key,
                'Content-Type': content_type,
            }
            
            if metadata:
                for k, v in metadata.items():
                    fields[f'x-amz-meta-{k}'] = v
            
            response = await client.generate_presigned_post(
                Bucket=self.bucket,
                Key=key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expires_in,
            )
            return response
    
    async def generate_presigned_download(
        self,
        key: str,
        filename: str | None = None,
        expires_in: int = 3600,
    ) -> str:
        """Generate presigned GET URL for download"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            config=self.config,
            **self.credentials,
        ) as client:
            params = {'Bucket': self.bucket, 'Key': key}
            
            if filename:
                params['ResponseContentDisposition'] = f'attachment; filename="{filename}"'
            
            return await client.generate_presigned_url(
                'get_object',
                Params=params,
                ExpiresIn=expires_in,
            )
    
    async def delete_object(self, key: str) -> None:
        """Delete object from S3"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            config=self.config,
            **self.credentials,
        ) as client:
            await client.delete_object(Bucket=self.bucket, Key=key)
    
    async def head_object(self, key: str) -> dict | None:
        """Get object metadata"""
        async with self.session.create_client(
            's3',
            endpoint_url=self.endpoint_url,
            config=self.config,
            **self.credentials,
        ) as client:
            try:
                return await client.head_object(Bucket=self.bucket, Key=key)
            except:
                return None


class StorageService:
    """Storage service combining S3 and PostgreSQL"""
    
    def __init__(
        self,
        session: AsyncSession,
        s3_provider: S3StorageProvider,
    ):
        self.session = session
        self.s3 = s3_provider
    
    async def create_upload(
        self,
        org_id: str,
        user_id: str,
        request: StorageFileCreate,
    ) -> PresignedUploadResponse:
        """Create a new file upload and return presigned URL"""
        file_id = str(uuid.uuid4())
        
        # Generate S3 key with tenant isolation
        date_prefix = datetime.now(UTC).strftime('%Y/%m/%d')
        s3_key = f"tenants/{org_id}/files/{date_prefix}/{file_id}/{request.filename}"
        
        # Calculate expiration
        expires_at = None
        if request.expires_in_hours:
            expires_at = datetime.now(UTC) + timedelta(hours=request.expires_in_hours)
        
        # Create DB record (status: pending)
        file_record = StorageFileORM(
            file_id=file_id,
            org_id=org_id,
            user_id=user_id,
            s3_bucket=self.s3.bucket,
            s3_key=s3_key,
            filename=request.filename,
            content_type=request.content_type,
            size_bytes=request.size_bytes,
            tags=request.tags,
            metadata_json=request.metadata,
            status='pending',
            expires_at=expires_at,
        )
        
        self.session.add(file_record)
        await self.session.commit()
        
        # Generate presigned URL
        presigned = await self.s3.generate_presigned_upload(
            key=s3_key,
            content_type=request.content_type,
            expires_in=3600,
            metadata={'org-id': org_id, 'user-id': user_id, 'file-id': file_id},
        )
        
        return PresignedUploadResponse(
            file_id=file_id,
            upload_url=presigned['url'],
            fields=presigned['fields'],
            expires_in=3600,
            s3_key=s3_key,
        )
    
    async def complete_upload(
        self,
        org_id: str,
        file_id: str,
    ) -> StorageFile:
        """Mark upload as complete after client uploads to S3"""
        # Get file record
        stmt = select(StorageFileORM).where(
            StorageFileORM.file_id == file_id,
            StorageFileORM.org_id == org_id,
            StorageFileORM.status == 'pending',
        )
        result = await self.session.execute(stmt)
        file_record = result.scalar_one_or_none()
        
        if not file_record:
            raise ValueError(f"File {file_id} not found or already uploaded")
        
        # Verify file exists in S3
        head = await self.s3.head_object(file_record.s3_key)
        if not head:
            raise ValueError(f"File not found in S3")
        
        # Update record
        file_record.status = 'uploaded'
        file_record.uploaded_at = datetime.now(UTC)
        file_record.size_bytes = head.get('ContentLength', 0)
        
        await self.session.commit()
        await self.session.refresh(file_record)
        
        return StorageFile.model_validate(file_record)
    
    async def get_download_url(
        self,
        org_id: str,
        file_id: str,
        expires_in: int = 3600,
    ) -> PresignedDownloadResponse:
        """Get presigned download URL"""
        file_record = await self._get_file(org_id, file_id)
        
        url = await self.s3.generate_presigned_download(
            key=file_record.s3_key,
            filename=file_record.filename,
            expires_in=expires_in,
        )
        
        return PresignedDownloadResponse(
            download_url=url,
            expires_in=expires_in,
            filename=file_record.filename,
            content_type=file_record.content_type,
            size_bytes=file_record.size_bytes,
        )
    
    async def delete_file(
        self,
        org_id: str,
        file_id: str,
        hard_delete: bool = False,
    ) -> None:
        """Delete a file (soft delete by default)"""
        file_record = await self._get_file(org_id, file_id)
        
        if hard_delete:
            # Delete from S3
            await self.s3.delete_object(file_record.s3_key)
            # Delete from DB
            await self.session.delete(file_record)
        else:
            # Soft delete
            file_record.status = 'deleted'
            file_record.deleted_at = datetime.now(UTC)
        
        await self.session.commit()
    
    async def list_files(
        self,
        org_id: str,
        request: StorageListRequest,
    ) -> tuple[list[StorageFile], int]:
        """List files with filtering"""
        stmt = select(StorageFileORM).where(
            StorageFileORM.org_id == org_id,
            StorageFileORM.status != 'deleted',
        )
        
        # Apply filters
        if request.tags:
            stmt = stmt.where(StorageFileORM.tags.overlap(request.tags))
        if request.status:
            stmt = stmt.where(StorageFileORM.status == request.status)
        if request.created_after:
            stmt = stmt.where(StorageFileORM.created_at >= request.created_after)
        if request.created_before:
            stmt = stmt.where(StorageFileORM.created_at <= request.created_before)
        
        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        
        # Apply pagination
        stmt = stmt.offset(request.offset).limit(request.limit)
        stmt = stmt.order_by(StorageFileORM.created_at.desc())
        
        result = await self.session.execute(stmt)
        files = [StorageFile.model_validate(f) for f in result.scalars().all()]
        
        return files, total
    
    async def get_quota(self, org_id: str) -> StorageQuota:
        """Get storage usage for organization"""
        # Get usage
        stmt = select(
            func.coalesce(func.sum(StorageFileORM.size_bytes), 0),
            func.count(StorageFileORM.file_id),
        ).where(
            StorageFileORM.org_id == org_id,
            StorageFileORM.status == 'uploaded',
        )
        
        result = await self.session.execute(stmt)
        used_bytes, file_count = result.one()
        
        # Get limits from organization settings
        # (In production, this would come from Organization.settings)
        max_bytes = 10 * 1024 * 1024 * 1024  # 10 GB default
        max_files = 10000  # 10k files default
        
        return StorageQuota(
            org_id=org_id,
            used_bytes=used_bytes,
            max_bytes=max_bytes,
            file_count=file_count,
            max_files=max_files,
        )
    
    async def _get_file(self, org_id: str, file_id: str) -> StorageFileORM:
        """Get file record by ID"""
        stmt = select(StorageFileORM).where(
            StorageFileORM.file_id == file_id,
            StorageFileORM.org_id == org_id,
            StorageFileORM.status != 'deleted',
        )
        result = await self.session.execute(stmt)
        file_record = result.scalar_one_or_none()
        
        if not file_record:
            raise ValueError(f"File {file_id} not found")
        
        return file_record
```

### 2.5 Implementation Tasks

| ID | Task | Priority | Effort | Dependencies | Files |
|----|------|----------|--------|--------------|-------|
| S3-001 | Create Pydantic models | P0 | 2h | - | `models/storage.py` |
| S3-002 | Create ORM model | P0 | 1h | S3-001 | `core/orm.py` |
| S3-003 | Create Alembic migration | P0 | 1h | S3-002 | `alembic/versions/` |
| S3-004 | Implement S3StorageProvider | P0 | 4h | - | `services/storage_service.py` |
| S3-005 | Implement StorageService | P0 | 6h | S3-004 | `services/storage_service.py` |
| S3-006 | Create API endpoints | P0 | 4h | S3-005 | `api/storage.py` |
| S3-007 | Add MinIO to docker-compose | P0 | 1h | - | `docker-compose.yml` |
| S3-008 | Add environment variables | P0 | 1h | - | `.env.example` |
| S3-009 | Add aiobotocore dependency | P0 | 0.5h | - | `pyproject.toml` |
| S3-010 | Implement quota checks | P1 | 2h | S3-005 | `services/storage_service.py` |
| S3-011 | File cleanup service | P1 | 3h | S3-005 | `services/storage_cleanup_service.py` |
| S3-012 | Unit tests (provider) | P0 | 3h | S3-004 | `tests/unit/test_services/` |
| S3-013 | Unit tests (service) | P0 | 3h | S3-005 | `tests/unit/test_services/` |
| S3-014 | Integration tests (API) | P1 | 4h | S3-006 | `tests/integration/test_api/` |
| S3-015 | E2E tests with MinIO | P2 | 3h | S3-014 | `tests/e2e/` |
| S3-016 | Documentation | P2 | 2h | All | `docs/storage.md` |
| S3-017 | RBAC integration | P1 | 2h | RBAC-006, S3-006 | `api/storage.py` |

**Total: ~40 hours**

---

## Feature 3: Rate Limiting

### 3.1 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Advanced Rate Limiting Architecture                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Request Flow                                                           │
│   ──────────                                                            │
│                                                                          │
│   HTTP Request                                                           │
│       │                                                                  │
│       ▼                                                                  │
│   ┌───────────────────────────────────────────────────────────┐         │
│   │              RateLimitMiddleware (Starlette)              │         │
│   │                                                            │         │
│   │  1. Extract key (API Key → User → Org → IP)               │         │
│   │  2. Classify endpoint (streaming, runs, write, read)       │         │
│   │  3. Call RateLimitEnforcer                                │         │
│   │  4. Return 429 or add X-RateLimit-* headers               │         │
│   └───────────────────────┬───────────────────────────────────┘         │
│                           │                                              │
│                           ▼                                              │
│   ┌───────────────────────────────────────────────────────────┐         │
│   │              RateLimitEnforcer (Service)                  │         │
│   │                                                            │         │
│   │  Rule Resolution Order (highest priority first):          │         │
│   │  1. API Key specific rule                                  │         │
│   │  2. User specific rule                                     │         │
│   │  3. Organization rule                                      │         │
│   │  4. Global default                                         │         │
│   └───────────────────────┬───────────────────────────────────┘         │
│                           │                                              │
│           ┌───────────────┼───────────────┐                             │
│           ▼               ▼               ▼                             │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                   │
│   │ Redis Cache  │ │ PostgreSQL   │ │ In-Memory    │                   │
│   │ (Counters)   │ │ (Rules)      │ │ (Fallback)   │                   │
│   └──────────────┘ └──────────────┘ └──────────────┘                   │
│                                                                          │
│   Rule Types:                                                            │
│   ───────────                                                           │
│   • Global defaults (env vars)                                          │
│   • Organization rules (rate_limit_rules table)                         │
│   • User override rules                                                  │
│   • API Key specific rules                                              │
│   • Endpoint pattern rules (/api/v1/*, /runs/*)                         │
│                                                                          │
│   Algorithms:                                                            │
│   ───────────                                                           │
│   • Fixed Window (current - simple, boundary issues)                    │
│   • Sliding Window (Lua script - recommended for accuracy)              │
│   • Token Bucket (optional - for burst handling)                        │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Database Schema

```sql
-- alembic/versions/20260105_add_rate_limit_rules.py

CREATE TABLE rate_limit_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Scope (hierarchical: api_key > user > org > global)
    org_id TEXT REFERENCES organizations(org_id) ON DELETE CASCADE,
    user_id TEXT,                        -- NULL = org-wide rule
    api_key_id TEXT,                     -- NULL = not API key specific
    
    -- Target
    endpoint_pattern TEXT,               -- NULL = all endpoints, or "/runs/*"
    endpoint_type TEXT,                  -- NULL or: streaming, runs, write, read
    
    -- Limits
    requests_per_minute INT,
    requests_per_hour INT NOT NULL,
    requests_per_day INT,
    burst_limit INT,                     -- Max requests in short burst
    
    -- Algorithm
    algorithm TEXT DEFAULT 'fixed_window',  -- fixed_window, sliding_window, token_bucket
    
    -- Metadata
    name TEXT,
    description TEXT,
    enabled BOOLEAN DEFAULT TRUE,
    priority INT DEFAULT 0,              -- Higher = checked first
    
    -- Audit
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    CONSTRAINT chk_scope CHECK (
        -- At least org_id must be set, or it's a global rule
        (org_id IS NOT NULL) OR (user_id IS NULL AND api_key_id IS NULL)
    )
);

CREATE INDEX idx_rate_limit_rules_org_id ON rate_limit_rules(org_id);
CREATE INDEX idx_rate_limit_rules_user_id ON rate_limit_rules(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_rate_limit_rules_api_key_id ON rate_limit_rules(api_key_id) WHERE api_key_id IS NOT NULL;
CREATE INDEX idx_rate_limit_rules_endpoint_type ON rate_limit_rules(endpoint_type);
CREATE INDEX idx_rate_limit_rules_priority ON rate_limit_rules(priority DESC);

-- Rate limit history for analytics (partitioned by month)
CREATE TABLE rate_limit_history (
    id UUID DEFAULT gen_random_uuid(),
    
    -- Key info
    key TEXT NOT NULL,                   -- e.g., "streaming:org:org-123"
    org_id TEXT,
    user_id TEXT,
    
    -- Request info
    endpoint_type TEXT NOT NULL,
    endpoint_path TEXT,
    
    -- Result
    allowed BOOLEAN NOT NULL,
    current_count INT NOT NULL,
    limit_value INT NOT NULL,
    
    -- Timing
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    window_reset_at TIMESTAMPTZ,
    
    PRIMARY KEY (id, timestamp)
) PARTITION BY RANGE (timestamp);

-- Create initial partitions
CREATE TABLE rate_limit_history_2026_01 PARTITION OF rate_limit_history
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE TABLE rate_limit_history_2026_02 PARTITION OF rate_limit_history
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');

-- Indexes on partitioned table
CREATE INDEX idx_rate_limit_history_org_timestamp 
    ON rate_limit_history(org_id, timestamp);
CREATE INDEX idx_rate_limit_history_allowed 
    ON rate_limit_history(allowed, timestamp);
```

### 3.3 Pydantic Models

```python
# src/agent_server/models/rate_limit_rules.py

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

Algorithm = Literal["fixed_window", "sliding_window", "token_bucket"]
EndpointType = Literal["streaming", "runs", "write", "read"]


class RateLimitRuleCreate(BaseModel):
    """Create a rate limit rule"""
    # Scope
    user_id: str | None = None
    api_key_id: str | None = None
    endpoint_pattern: str | None = None
    endpoint_type: EndpointType | None = None
    
    # Limits
    requests_per_minute: int | None = Field(default=None, ge=1)
    requests_per_hour: int = Field(..., ge=1)
    requests_per_day: int | None = Field(default=None, ge=1)
    burst_limit: int | None = Field(default=None, ge=1)
    
    # Config
    algorithm: Algorithm = "fixed_window"
    name: str | None = None
    description: str | None = None
    enabled: bool = True
    priority: int = Field(default=0, ge=0, le=100)


class RateLimitRule(BaseModel):
    """Rate limit rule"""
    id: str
    org_id: str | None
    user_id: str | None
    api_key_id: str | None
    endpoint_pattern: str | None
    endpoint_type: str | None
    requests_per_minute: int | None
    requests_per_hour: int
    requests_per_day: int | None
    burst_limit: int | None
    algorithm: str
    name: str | None
    description: str | None
    enabled: bool
    priority: int
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RateLimitRuleUpdate(BaseModel):
    """Update a rate limit rule"""
    requests_per_minute: int | None = None
    requests_per_hour: int | None = None
    requests_per_day: int | None = None
    burst_limit: int | None = None
    algorithm: Algorithm | None = None
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    priority: int | None = None


class RateLimitCheckResult(BaseModel):
    """Result of rate limit check"""
    allowed: bool
    limit: int
    remaining: int
    reset_at: int  # Unix timestamp
    retry_after: int | None = None  # Seconds until retry (only if not allowed)
    rule_id: str | None = None
    algorithm: str


class RateLimitUsage(BaseModel):
    """Current usage for a key"""
    key: str
    endpoint_type: str
    current: int
    limit: int
    remaining: int
    reset_in: int  # Seconds until reset
    window: str  # "minute", "hour", "day"


class RateLimitAnalytics(BaseModel):
    """Rate limit analytics summary"""
    org_id: str
    period_start: datetime
    period_end: datetime
    total_requests: int
    allowed_requests: int
    denied_requests: int
    denial_rate: float
    top_denied_endpoints: list[dict]
    peak_hour: int  # Hour with most requests
```

### 3.4 Service Layer

```python
# src/agent_server/services/rate_limit_rule_service.py

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.orm import RateLimitRule as RulORM
from ..core.cache import cache_manager
from ..models.rate_limit_rules import (
    RateLimitRule, RateLimitRuleCreate, RateLimitRuleUpdate,
)


class RateLimitRuleService:
    """CRUD service for rate limit rules"""
    
    CACHE_TTL = 300  # 5 minutes
    CACHE_PREFIX = "rate_rules"
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create_rule(
        self,
        org_id: str,
        request: RateLimitRuleCreate,
        created_by: str,
    ) -> RateLimitRule:
        """Create a new rate limit rule"""
        rule = RuleORM(
            org_id=org_id,
            user_id=request.user_id,
            api_key_id=request.api_key_id,
            endpoint_pattern=request.endpoint_pattern,
            endpoint_type=request.endpoint_type,
            requests_per_minute=request.requests_per_minute,
            requests_per_hour=request.requests_per_hour,
            requests_per_day=request.requests_per_day,
            burst_limit=request.burst_limit,
            algorithm=request.algorithm,
            name=request.name,
            description=request.description,
            enabled=request.enabled,
            priority=request.priority,
            created_by=created_by,
        )
        
        self.session.add(rule)
        await self.session.commit()
        await self.session.refresh(rule)
        
        # Invalidate cache
        await self._invalidate_cache(org_id)
        
        return RateLimitRule.model_validate(rule)
    
    async def get_rules_for_request(
        self,
        org_id: str | None,
        user_id: str | None,
        api_key_id: str | None,
        endpoint_type: str,
    ) -> list[RateLimitRule]:
        """
        Get applicable rules for a request, ordered by priority.
        
        Returns rules that match the request context,
        sorted by priority (highest first).
        """
        # Check cache
        cache_key = f"{self.CACHE_PREFIX}:{org_id}:{endpoint_type}"
        cached = await cache_manager.get(cache_key)
        if cached:
            all_rules = [RateLimitRule.model_validate(r) for r in cached]
        else:
            # Fetch from DB
            stmt = select(RuleORM).where(
                RuleORM.enabled == True,
                or_(
                    RuleORM.org_id == org_id,
                    RuleORM.org_id.is_(None),  # Global rules
                ),
                or_(
                    RuleORM.endpoint_type == endpoint_type,
                    RuleORM.endpoint_type.is_(None),  # All endpoints
                ),
            ).order_by(RuleORM.priority.desc())
            
            result = await self.session.execute(stmt)
            all_rules = [RateLimitRule.model_validate(r) for r in result.scalars().all()]
            
            # Cache
            await cache_manager.set(
                cache_key,
                [r.model_dump() for r in all_rules],
                ttl=self.CACHE_TTL,
            )
        
        # Filter by user/api_key scope
        applicable = []
        for rule in all_rules:
            # API key specific rule
            if rule.api_key_id:
                if rule.api_key_id == api_key_id:
                    applicable.append(rule)
                continue
            
            # User specific rule
            if rule.user_id:
                if rule.user_id == user_id:
                    applicable.append(rule)
                continue
            
            # Org-wide or global rule
            applicable.append(rule)
        
        return applicable
    
    async def _invalidate_cache(self, org_id: str) -> None:
        """Invalidate all cached rules for an org"""
        for endpoint_type in ["streaming", "runs", "write", "read"]:
            cache_key = f"{self.CACHE_PREFIX}:{org_id}:{endpoint_type}"
            await cache_manager.delete(cache_key)


# src/agent_server/services/rate_limit_enforcer.py

import time
from dataclasses import dataclass

from ..core.cache import cache_manager
from ..models.rate_limit_rules import RateLimitCheckResult, RateLimitRule


# Lua script for sliding window rate limiting
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local window = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

-- Remove old entries
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

-- Count current requests
local current = redis.call('ZCARD', key)

if current < limit then
    -- Add new request with timestamp as score and value
    redis.call('ZADD', key, now, now .. ':' .. math.random())
    redis.call('EXPIRE', key, window)
    return {1, limit - current - 1, now + window}
else
    -- Get oldest entry to calculate reset time
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local reset_at = now + window
    if oldest and #oldest >= 2 then
        reset_at = tonumber(oldest[2]) + window
    end
    return {0, 0, reset_at}
end
"""


class RateLimitEnforcer:
    """Enforces rate limits using Redis"""
    
    def __init__(self, rule_service: RateLimitRuleService):
        self.rule_service = rule_service
        self._sliding_window_script = None
    
    async def check_limit(
        self,
        org_id: str | None,
        user_id: str | None,
        api_key_id: str | None,
        endpoint_type: str,
        key: str,
    ) -> RateLimitCheckResult:
        """
        Check rate limit for a request.
        
        1. Get applicable rules
        2. Use highest priority rule
        3. Check against Redis counter
        4. Return result
        """
        # Get applicable rules
        rules = await self.rule_service.get_rules_for_request(
            org_id, user_id, api_key_id, endpoint_type
        )
        
        if not rules:
            # No rules = no limit (allow all)
            return RateLimitCheckResult(
                allowed=True,
                limit=0,
                remaining=0,
                reset_at=0,
                algorithm="none",
            )
        
        # Use highest priority rule
        rule = rules[0]
        
        # Choose limit based on window
        now = int(time.time())
        if rule.requests_per_minute:
            limit = rule.requests_per_minute
            window = 60
        else:
            limit = rule.requests_per_hour
            window = 3600
        
        # Execute rate limit check based on algorithm
        if rule.algorithm == "sliding_window":
            result = await self._check_sliding_window(key, window, limit, now)
        elif rule.algorithm == "token_bucket":
            result = await self._check_token_bucket(key, limit, rule.burst_limit or limit)
        else:  # fixed_window
            result = await self._check_fixed_window(key, window, limit, now)
        
        return RateLimitCheckResult(
            allowed=result["allowed"],
            limit=limit,
            remaining=result["remaining"],
            reset_at=result["reset_at"],
            retry_after=result.get("retry_after"),
            rule_id=str(rule.id),
            algorithm=rule.algorithm,
        )
    
    async def _check_sliding_window(
        self,
        key: str,
        window: int,
        limit: int,
        now: int,
    ) -> dict:
        """Sliding window rate limit using Lua script."""
        redis = await cache_manager.get_redis()
        
        if redis is None:
            # Fallback to fixed window if Redis unavailable
            return await self._check_fixed_window(key, window, limit, now)
        
        # Execute Lua script
        result = await redis.eval(
            SLIDING_WINDOW_LUA,
            keys=[f"ratelimit:{key}"],
            args=[window, limit, now],
        )
        
        allowed, remaining, reset_at = result
        return {
            "allowed": bool(allowed),
            "remaining": remaining,
            "reset_at": reset_at,
            "retry_after": (reset_at - now) if not allowed else None,
        }
    
    async def _check_fixed_window(
        self,
        key: str,
        window: int,
        limit: int,
        now: int,
    ) -> dict:
        """Fixed window rate limit (simpler, boundary issues)."""
        window_key = f"ratelimit:{key}:{now // window}"
        
        redis = await cache_manager.get_redis()
        if redis is None:
            # In-memory fallback (per-process, not distributed)
            return await self._check_in_memory(key, window, limit, now)
        
        # Increment counter
        count = await redis.incr(window_key)
        
        # Set expiration on first request
        if count == 1:
            await redis.expire(window_key, window)
        
        reset_at = ((now // window) + 1) * window
        
        return {
            "allowed": count <= limit,
            "remaining": max(0, limit - count),
            "reset_at": reset_at,
            "retry_after": (reset_at - now) if count > limit else None,
        }
    
    async def _check_token_bucket(
        self,
        key: str,
        rate: int,
        burst: int,
    ) -> dict:
        """Token bucket algorithm for burst handling."""
        redis = await cache_manager.get_redis()
        if redis is None:
            return {"allowed": True, "remaining": burst, "reset_at": 0}
        
        bucket_key = f"ratelimit:bucket:{key}"
        now = time.time()
        
        # Get current bucket state
        data = await redis.hgetall(bucket_key)
        
        if not data:
            # Initialize bucket
            tokens = burst - 1
            await redis.hset(bucket_key, mapping={"tokens": tokens, "last": now})
            await redis.expire(bucket_key, 3600)
            return {"allowed": True, "remaining": tokens, "reset_at": int(now + 1)}
        
        # Calculate tokens to add since last request
        tokens = float(data.get("tokens", burst))
        last = float(data.get("last", now))
        elapsed = now - last
        
        # Refill tokens (1 token per second * rate/60)
        tokens = min(burst, tokens + elapsed * (rate / 60))
        
        if tokens >= 1:
            tokens -= 1
            await redis.hset(bucket_key, mapping={"tokens": tokens, "last": now})
            return {"allowed": True, "remaining": int(tokens), "reset_at": int(now + 1)}
        else:
            # Calculate when next token available
            wait_time = (1 - tokens) / (rate / 60)
            return {
                "allowed": False,
                "remaining": 0,
                "reset_at": int(now + wait_time),
                "retry_after": int(wait_time) + 1,
            }
    
    # In-memory fallback (for single-instance deployments without Redis)
    _memory_counters: dict = {}
    
    async def _check_in_memory(
        self,
        key: str,
        window: int,
        limit: int,
        now: int,
    ) -> dict:
        """In-memory rate limiting (single process only)."""
        window_key = f"{key}:{now // window}"
        
        # Clean old windows
        cutoff = now - window
        self._memory_counters = {
            k: v for k, v in self._memory_counters.items()
            if int(k.split(":")[-1]) * window > cutoff
        }
        
        # Increment
        count = self._memory_counters.get(window_key, 0) + 1
        self._memory_counters[window_key] = count
        
        reset_at = ((now // window) + 1) * window
        
        return {
            "allowed": count <= limit,
            "remaining": max(0, limit - count),
            "reset_at": reset_at,
            "retry_after": (reset_at - now) if count > limit else None,
        }
    
    async def record_history(
        self,
        key: str,
        org_id: str | None,
        user_id: str | None,
        endpoint_type: str,
        endpoint_path: str,
        result: RateLimitCheckResult,
    ) -> None:
        """Record rate limit check for analytics (async, non-blocking)."""
        # Fire-and-forget to avoid adding latency
        # In production, use a background task queue
        try:
            from ..core.orm import RateLimitHistory
            from ..core.database import DatabaseManager
            
            db = DatabaseManager.get_instance()
            async with db.get_session() as session:
                history = RateLimitHistory(
                    key=key,
                    org_id=org_id,
                    user_id=user_id,
                    endpoint_type=endpoint_type,
                    endpoint_path=endpoint_path,
                    allowed=result.allowed,
                    current_count=result.limit - result.remaining,
                    limit_value=result.limit,
                    window_reset_at=datetime.fromtimestamp(result.reset_at, UTC) if result.reset_at else None,
                )
                session.add(history)
                await session.commit()
        except Exception:
            pass  # Don't fail request on history recording error


# src/agent_server/services/rate_limit_analytics_service.py

from datetime import datetime, timedelta, UTC
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.orm import RateLimitHistory
from ..models.rate_limit_rules import RateLimitAnalytics


class RateLimitAnalyticsService:
    """Analytics service for rate limit data."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_analytics(
        self,
        org_id: str,
        period_hours: int = 24,
    ) -> RateLimitAnalytics:
        """Get rate limit analytics for an organization."""
        now = datetime.now(UTC)
        period_start = now - timedelta(hours=period_hours)
        
        # Base query
        base_filter = and_(
            RateLimitHistory.org_id == org_id,
            RateLimitHistory.timestamp >= period_start,
        )
        
        # Total requests
        total_stmt = select(func.count()).where(base_filter)
        total_requests = (await self.session.execute(total_stmt)).scalar_one()
        
        # Allowed requests
        allowed_stmt = select(func.count()).where(
            and_(base_filter, RateLimitHistory.allowed == True)
        )
        allowed_requests = (await self.session.execute(allowed_stmt)).scalar_one()
        
        # Denied requests
        denied_requests = total_requests - allowed_requests
        
        # Top denied endpoints
        top_denied_stmt = (
            select(
                RateLimitHistory.endpoint_path,
                func.count().label("count"),
            )
            .where(and_(base_filter, RateLimitHistory.allowed == False))
            .group_by(RateLimitHistory.endpoint_path)
            .order_by(func.count().desc())
            .limit(10)
        )
        top_denied_result = await self.session.execute(top_denied_stmt)
        top_denied_endpoints = [
            {"endpoint": row[0], "denied_count": row[1]}
            for row in top_denied_result.all()
        ]
        
        # Peak hour
        peak_hour_stmt = (
            select(
                func.extract("hour", RateLimitHistory.timestamp).label("hour"),
                func.count().label("count"),
            )
            .where(base_filter)
            .group_by(func.extract("hour", RateLimitHistory.timestamp))
            .order_by(func.count().desc())
            .limit(1)
        )
        peak_hour_result = await self.session.execute(peak_hour_stmt)
        peak_row = peak_hour_result.first()
        peak_hour = int(peak_row[0]) if peak_row else 0
        
        return RateLimitAnalytics(
            org_id=org_id,
            period_start=period_start,
            period_end=now,
            total_requests=total_requests,
            allowed_requests=allowed_requests,
            denied_requests=denied_requests,
            denial_rate=denied_requests / total_requests if total_requests > 0 else 0.0,
            top_denied_endpoints=top_denied_endpoints,
            peak_hour=peak_hour,
        )
    
    async def get_usage_by_key(
        self,
        org_id: str,
        key: str,
    ) -> dict:
        """Get current usage for a specific rate limit key."""
        # This would query Redis for current counter values
        # Implementation depends on the algorithm being used
        pass
```

### 3.5 API Endpoints

```python
# src/agent_server/api/rate_limit_rules.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.orm import get_session
from ..core.auth_deps import get_current_user
from ..core.rbac import require_permission, require_role
from ..models.auth import User
from ..models.rate_limit_rules import (
    RateLimitRule, RateLimitRuleCreate, RateLimitRuleUpdate,
    RateLimitUsage, RateLimitAnalytics,
)
from ..services.rate_limit_rule_service import RateLimitRuleService
from ..services.rate_limit_analytics_service import RateLimitAnalyticsService

router = APIRouter(prefix="/organizations/{org_id}/quotas", tags=["Rate Limits"])

# ==================== Rule Management ====================

@router.get("/rules", response_model=list[RateLimitRule])
@require_permission("quotas:read")
async def list_rules(
    org_id: str,
    endpoint_type: str | None = None,
    enabled_only: bool = True,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """List all rate limit rules for organization"""
    service = RateLimitRuleService(session)
    return await service.list_rules(org_id, endpoint_type, enabled_only)


@router.post("/rules", response_model=RateLimitRule, status_code=201)
@require_role("owner", "admin")
async def create_rule(
    org_id: str,
    request: RateLimitRuleCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Create a new rate limit rule"""
    service = RateLimitRuleService(session)
    return await service.create_rule(org_id, request, user.identity)


@router.get("/rules/{rule_id}", response_model=RateLimitRule)
@require_permission("quotas:read")
async def get_rule(
    org_id: str,
    rule_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get a specific rate limit rule"""
    service = RateLimitRuleService(session)
    rule = await service.get_rule(org_id, rule_id)
    if not rule:
        raise HTTPException(404, f"Rule {rule_id} not found")
    return rule


@router.patch("/rules/{rule_id}", response_model=RateLimitRule)
@require_role("owner", "admin")
async def update_rule(
    org_id: str,
    rule_id: str,
    request: RateLimitRuleUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update a rate limit rule"""
    service = RateLimitRuleService(session)
    return await service.update_rule(org_id, rule_id, request)


@router.delete("/rules/{rule_id}", status_code=204)
@require_role("owner", "admin")
async def delete_rule(
    org_id: str,
    rule_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a rate limit rule"""
    service = RateLimitRuleService(session)
    await service.delete_rule(org_id, rule_id)


# ==================== Usage & Analytics ====================

@router.get("/usage", response_model=list[RateLimitUsage])
@require_permission("quotas:read")
async def get_current_usage(
    org_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get current rate limit usage for organization"""
    service = RateLimitRuleService(session)
    return await service.get_current_usage(org_id)


@router.get("/analytics", response_model=RateLimitAnalytics)
@require_permission("quotas:read")
async def get_analytics(
    org_id: str,
    period_hours: int = Query(default=24, ge=1, le=720),  # Max 30 days
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get rate limit analytics for organization"""
    service = RateLimitAnalyticsService(session)
    return await service.get_analytics(org_id, period_hours)
```

### 3.6 Middleware Integration

```python
# src/agent_server/middleware/rate_limit.py (updated)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse

from ..services.rate_limit_enforcer import RateLimitEnforcer
from ..services.rate_limit_rule_service import RateLimitRuleService


class AdvancedRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Advanced rate limiting middleware with DB-controlled rules.
    
    Replaces the environment variable-based SlowAPI approach
    with dynamic, per-org rate limit rules from PostgreSQL.
    """
    
    ENDPOINT_TYPE_MAP = {
        "/runs/stream": "streaming",
        "/threads/*/runs/stream": "streaming",
        "/runs": "runs",
        "/threads/*/runs": "runs",
        "/assistants": "write",
        "/threads": "write",
        "/store": "write",
    }
    
    def __init__(self, app, rule_service: RateLimitRuleService):
        super().__init__(app)
        self.enforcer = RateLimitEnforcer(rule_service)
    
    async def dispatch(self, request: Request, call_next):
        # Skip health checks
        if request.url.path in ("/health", "/ready", "/metrics"):
            return await call_next(request)
        
        # Extract identity
        user = getattr(request.state, "user", None)
        org_id = user.org_id if user else None
        user_id = user.identity if user else None
        api_key_id = request.headers.get("X-API-Key-ID")
        
        # Classify endpoint
        endpoint_type = self._classify_endpoint(request.url.path, request.method)
        
        # Build rate limit key
        key = self._build_key(endpoint_type, org_id, user_id, api_key_id, request)
        
        # Check rate limit
        result = await self.enforcer.check_limit(
            org_id, user_id, api_key_id, endpoint_type, key
        )
        
        # Record for analytics (non-blocking)
        await self.enforcer.record_history(
            key, org_id, user_id, endpoint_type, request.url.path, result
        )
        
        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded. Try again in {result.retry_after} seconds.",
                    "retry_after": result.retry_after,
                },
                headers={
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_at),
                    "Retry-After": str(result.retry_after),
                },
            )
        
        # Proceed with request
        response = await call_next(request)
        
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(result.reset_at)
        
        return response
    
    def _classify_endpoint(self, path: str, method: str) -> str:
        """Classify endpoint into type for rate limiting."""
        if "stream" in path:
            return "streaming"
        if "/runs" in path:
            return "runs"
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            return "write"
        return "read"
    
    def _build_key(
        self,
        endpoint_type: str,
        org_id: str | None,
        user_id: str | None,
        api_key_id: str | None,
        request: Request,
    ) -> str:
        """Build rate limit key based on identity."""
        if api_key_id:
            return f"{endpoint_type}:apikey:{api_key_id}"
        if user_id and org_id:
            return f"{endpoint_type}:user:{org_id}:{user_id}"
        if org_id:
            return f"{endpoint_type}:org:{org_id}"
        # Fallback to IP
        client_ip = request.client.host if request.client else "unknown"
        return f"{endpoint_type}:ip:{client_ip}"
```

### 3.7 Implementation Tasks

| ID | Task | Priority | Effort | Dependencies | Files |
|----|------|----------|--------|--------------|-------|
| RL-001 | Create Pydantic models | P0 | 2h | - | `models/rate_limit_rules.py` |
| RL-002 | Create ORM models | P0 | 2h | RL-001 | `core/orm.py` |
| RL-003 | Create Alembic migration | P0 | 1h | RL-002 | `alembic/versions/` |
| RL-004 | Create partition management | P1 | 2h | RL-003 | `services/partition_manager.py` |
| RL-005 | Implement RateLimitRuleService | P0 | 4h | RL-002 | `services/rate_limit_rule_service.py` |
| RL-006 | Implement RateLimitEnforcer | P0 | 6h | RL-005 | `services/rate_limit_enforcer.py` |
| RL-007 | Implement sliding window Lua | P0 | 2h | RL-006 | `services/rate_limit_enforcer.py` |
| RL-008 | Implement token bucket | P2 | 2h | RL-006 | `services/rate_limit_enforcer.py` |
| RL-009 | Implement in-memory fallback | P1 | 1h | RL-006 | `services/rate_limit_enforcer.py` |
| RL-010 | Create API endpoints | P0 | 3h | RL-005 | `api/rate_limit_rules.py` |
| RL-011 | Create middleware | P0 | 3h | RL-006 | `middleware/rate_limit.py` |
| RL-012 | Implement analytics service | P1 | 3h | RL-002 | `services/rate_limit_analytics_service.py` |
| RL-013 | Unit tests (service) | P0 | 3h | RL-005 | `tests/unit/test_services/` |
| RL-014 | Unit tests (enforcer) | P0 | 3h | RL-006 | `tests/unit/test_services/` |
| RL-015 | Integration tests (API) | P1 | 3h | RL-010 | `tests/integration/test_api/` |
| RL-016 | Load testing | P1 | 2h | RL-011 | `tests/load/` |
| RL-017 | Documentation | P2 | 2h | All | `docs/rate-limiting.md` |

**Total: ~35 hours**

### 3.8 Migration Strategy (Env Vars → DB Rules)

```python
# scripts/migrate_rate_limits.py

"""
Migration script to convert environment variable rate limits to DB rules.

Usage:
    python scripts/migrate_rate_limits.py --org-id <org_id> --dry-run
    python scripts/migrate_rate_limits.py --org-id <org_id> --execute
"""

import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

async def migrate_env_to_db(org_id: str, dry_run: bool = True):
    """Migrate environment variable rate limits to database rules."""
    
    # Read current env vars
    env_limits = {
        "streaming": {
            "per_minute": int(os.getenv("RATE_LIMIT_STREAMING_PER_MINUTE", 10)),
            "per_hour": int(os.getenv("RATE_LIMIT_STREAMING_PER_HOUR", 100)),
        },
        "runs": {
            "per_minute": int(os.getenv("RATE_LIMIT_RUNS_PER_MINUTE", 30)),
            "per_hour": int(os.getenv("RATE_LIMIT_RUNS_PER_HOUR", 500)),
        },
        "write": {
            "per_minute": int(os.getenv("RATE_LIMIT_WRITE_PER_MINUTE", 60)),
            "per_hour": int(os.getenv("RATE_LIMIT_WRITE_PER_HOUR", 1000)),
        },
        "read": {
            "per_minute": int(os.getenv("RATE_LIMIT_READ_PER_MINUTE", 120)),
            "per_hour": int(os.getenv("RATE_LIMIT_READ_PER_HOUR", 3000)),
        },
    }
    
    rules_to_create = []
    for endpoint_type, limits in env_limits.items():
        rules_to_create.append({
            "org_id": org_id,
            "endpoint_type": endpoint_type,
            "requests_per_minute": limits["per_minute"],
            "requests_per_hour": limits["per_hour"],
            "algorithm": "sliding_window",
            "name": f"Default {endpoint_type} limit (migrated from env)",
            "enabled": True,
            "priority": 10,  # Low priority, can be overridden
        })
    
    if dry_run:
        print("DRY RUN - Would create the following rules:")
        for rule in rules_to_create:
            print(f"  - {rule['endpoint_type']}: {rule['requests_per_minute']}/min, {rule['requests_per_hour']}/hr")
        return
    
    # Create rules in database
    # ... (actual DB insert code)
    print(f"Created {len(rules_to_create)} rate limit rules for org {org_id}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("Must specify --dry-run or --execute")
        exit(1)
    
    asyncio.run(migrate_env_to_db(args.org_id, dry_run=args.dry_run))
```

---

## Implementation Schedule

### Phase 1: Foundation (Week 1-2)

```
Week 1:
├── Day 1-2: RBAC Database & Models
│   ├── RBAC-001: Pydantic models
│   ├── RBAC-002: ORM models
│   └── RBAC-003: Alembic migration
│
├── Day 3-4: RBAC Core Services
│   ├── RBAC-004: PermissionService
│   └── RBAC-005: RBACService
│
└── Day 5: RBAC Integration
    ├── RBAC-006: Decorators
    └── RBAC-008: Seed system roles

Week 2:
├── Day 1-2: Rate Limiting Database & Models
│   ├── RL-001: Pydantic models
│   ├── RL-002: ORM models
│   └── RL-003: Alembic migration
│
├── Day 3-4: Rate Limiting Core
│   ├── RL-005: RateLimitRuleService
│   ├── RL-006: RateLimitEnforcer
│   └── RL-007: Sliding window Lua
│
└── Day 5: Rate Limiting Integration
    ├── RL-010: API endpoints
    └── RL-011: Middleware
```

### Phase 2: S3 Storage (Week 3)

```
Week 3:
├── Day 1: S3 Foundation
│   ├── S3-001: Pydantic models
│   ├── S3-002: ORM models
│   ├── S3-003: Alembic migration
│   └── S3-007: MinIO docker-compose
│
├── Day 2-3: S3 Core Services
│   ├── S3-004: S3StorageProvider
│   └── S3-005: StorageService
│
├── Day 4: S3 API & Integration
│   ├── S3-006: API endpoints
│   └── S3-017: RBAC integration
│
└── Day 5: Buffer / Catch-up
```

### Phase 3: Testing & Polish (Week 4)

```
Week 4:
├── Day 1-2: Unit Tests
│   ├── RBAC-012: RBAC unit tests
│   ├── RL-013, RL-014: Rate limit tests
│   └── S3-012, S3-013: Storage tests
│
├── Day 3: Integration Tests
│   ├── RBAC-013: RBAC integration
│   ├── RL-015: Rate limit integration
│   └── S3-014: Storage integration
│
├── Day 4: E2E Tests & Load Testing
│   ├── RBAC-014: RBAC E2E
│   ├── RL-016: Load testing
│   └── S3-015: S3 E2E with MinIO
│
└── Day 5: Documentation & Release
    ├── RBAC-015: RBAC docs
    ├── RL-017: Rate limit docs
    └── S3-016: Storage docs
```

### Gantt Chart (Simplified)

```
Feature          | Week 1 | Week 2 | Week 3 | Week 4 |
-----------------+--------+--------+--------+--------+
RBAC DB/Models   | ██████ |        |        |        |
RBAC Services    | ██████ |        |        |        |
RBAC API         |    ████|        |        |        |
Rate Limit DB    |        | ██████ |        |        |
Rate Limit Core  |        | ██████ |        |        |
Rate Limit API   |        |    ████|        |        |
S3 DB/Models     |        |        | ████   |        |
S3 Services      |        |        | ██████ |        |
S3 API           |        |        |    ████|        |
Unit Tests       |        |        |        | ████   |
Integration      |        |        |        |   ████ |
E2E & Load       |        |        |        |    ████|
Documentation    |        |        |        |     ███|
```

---

## Risk Mitigation

### Technical Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Redis unavailable | Rate limiting fails | Medium | In-memory fallback implemented |
| S3/MinIO unavailable | File uploads fail | Low | Health check + circuit breaker |
| Permission cache stale | Security bypass | Medium | Short TTL (5 min) + manual invalidation |
| DB migration failure | Service downtime | Low | Test in staging, rollback scripts |
| Sliding window Lua complexity | Bugs in rate limiting | Medium | Extensive unit tests, fallback to fixed window |

### Operational Risks

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Rate limit too aggressive | User frustration | Medium | Start with generous limits, monitor analytics |
| Storage quota exhausted | Upload failures | Low | Proactive alerts, quota dashboards |
| Role misconfiguration | Access issues | Medium | Audit logging, role preview before apply |
| Partition table growth | DB performance | Low | Auto-partition creation, retention policy |

### Rollback Strategy

Each feature includes a rollback plan:

1. **RBAC**: Feature flag to disable permission checks, fall back to role-only
2. **Rate Limiting**: Environment variable to bypass DB rules, use SlowAPI fallback
3. **S3 Storage**: Feature flag to disable storage endpoints, files remain in S3

---

## Feature Flags

```python
# src/agent_server/core/feature_flags.py

from pydantic import BaseModel
import os


class FeatureFlags(BaseModel):
    """Feature flags for gradual rollout."""
    
    # RBAC
    rbac_enabled: bool = True
    rbac_permission_checks_enabled: bool = True  # Can disable just permission checks
    rbac_cache_enabled: bool = True
    
    # Rate Limiting
    rate_limit_db_rules_enabled: bool = True  # False = use env vars
    rate_limit_sliding_window_enabled: bool = True  # False = fixed window
    rate_limit_analytics_enabled: bool = True
    
    # S3 Storage
    storage_enabled: bool = True
    storage_presigned_urls_enabled: bool = True
    storage_quota_checks_enabled: bool = True
    
    @classmethod
    def from_env(cls) -> "FeatureFlags":
        return cls(
            rbac_enabled=os.getenv("FF_RBAC_ENABLED", "true").lower() == "true",
            rbac_permission_checks_enabled=os.getenv("FF_RBAC_PERMISSION_CHECKS", "true").lower() == "true",
            rate_limit_db_rules_enabled=os.getenv("FF_RATE_LIMIT_DB_RULES", "true").lower() == "true",
            rate_limit_sliding_window_enabled=os.getenv("FF_RATE_LIMIT_SLIDING_WINDOW", "true").lower() == "true",
            storage_enabled=os.getenv("FF_STORAGE_ENABLED", "true").lower() == "true",
        )


# Global instance
feature_flags = FeatureFlags.from_env()
```

### Usage in Code

```python
# Example: Conditional permission check

from ..core.feature_flags import feature_flags

async def check_access(user, resource, action):
    if not feature_flags.rbac_enabled:
        # Fall back to simple role check
        return user.role in ("owner", "admin", "member")
    
    if not feature_flags.rbac_permission_checks_enabled:
        # RBAC enabled but permission checks disabled
        return True
    
    # Full permission check
    return await permission_service.check_permission(
        user.identity, user.org_id, f"{resource}:{action}"
    )
```

---

## Critical Constraints (MUST NOT)

### Security Constraints

| Constraint | Reason |
|------------|--------|
| NEVER store S3 credentials in database | Use environment variables or secrets manager |
| NEVER expose presigned URLs in logs | URLs contain auth signatures |
| NEVER bypass permission checks in production | Security risk |
| NEVER allow `*` wildcard in custom roles | Only system roles can have wildcard |

### Performance Constraints

| Constraint | Reason |
|------------|--------|
| NEVER call DB for every permission check | Must use caching |
| NEVER block on rate limit history recording | Async/fire-and-forget |
| NEVER skip Redis for sliding window in prod | In-memory is single-process only |
| NEVER query rate_limit_history without timestamp filter | Partitioned table requires it |

### Data Integrity Constraints

| Constraint | Reason |
|------------|--------|
| NEVER delete system roles | They are foundational |
| NEVER allow negative rate limits | Validation required |
| NEVER orphan S3 objects | Clean up DB record = clean up S3 |
| NEVER modify rate_limit_history directly | It's append-only for audit |

---

## Appendix: Environment Variables

### New Environment Variables

```bash
# .env.example additions

# === RBAC ===
# Cache TTL for permission lookups (seconds)
RBAC_CACHE_TTL=300

# === Rate Limiting ===
# Enable DB-based rules (false = use env var limits)
RATE_LIMIT_USE_DB_RULES=true

# Fallback limits (used when DB unavailable or FF disabled)
RATE_LIMIT_STREAMING_PER_MINUTE=10
RATE_LIMIT_STREAMING_PER_HOUR=100
RATE_LIMIT_RUNS_PER_MINUTE=30
RATE_LIMIT_RUNS_PER_HOUR=500
RATE_LIMIT_WRITE_PER_MINUTE=60
RATE_LIMIT_WRITE_PER_HOUR=1000
RATE_LIMIT_READ_PER_MINUTE=120
RATE_LIMIT_READ_PER_HOUR=3000

# === S3 Storage ===
S3_ENDPOINT_URL=http://localhost:9000  # MinIO for local dev
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_BUCKET=langgraph-files
S3_REGION=us-east-1
S3_PRESIGNED_URL_EXPIRY=3600  # Seconds

# === Feature Flags ===
FF_RBAC_ENABLED=true
FF_RBAC_PERMISSION_CHECKS=true
FF_RATE_LIMIT_DB_RULES=true
FF_RATE_LIMIT_SLIDING_WINDOW=true
FF_STORAGE_ENABLED=true
```

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-01-05 | AI Assistant | Initial version with RBAC, S3, Rate Limiting |