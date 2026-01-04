"""RBAC (Role-Based Access Control) Pydantic Models.

Permission String Format: {resource}:{action}
Examples: assistants:read, threads:*, organization:manage_members, * (superuser)

System Roles: owner, admin, developer, viewer, api_user
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Permission(str, Enum):
    """Fine-grained permissions. Format: {resource}:{action}. Wildcards: resource:* or *"""

    ASSISTANTS_READ = "assistants:read"
    ASSISTANTS_WRITE = "assistants:write"
    ASSISTANTS_DELETE = "assistants:delete"
    ASSISTANTS_ALL = "assistants:*"

    THREADS_READ = "threads:read"
    THREADS_WRITE = "threads:write"
    THREADS_DELETE = "threads:delete"
    THREADS_ALL = "threads:*"

    RUNS_READ = "runs:read"
    RUNS_CREATE = "runs:create"
    RUNS_CANCEL = "runs:cancel"
    RUNS_DELETE = "runs:delete"
    RUNS_ALL = "runs:*"

    STORE_READ = "store:read"
    STORE_WRITE = "store:write"
    STORE_DELETE = "store:delete"
    STORE_ALL = "store:*"

    CRONS_READ = "crons:read"
    CRONS_WRITE = "crons:write"
    CRONS_DELETE = "crons:delete"
    CRONS_ALL = "crons:*"

    ORG_READ = "organization:read"
    ORG_UPDATE = "organization:update"
    ORG_MANAGE_MEMBERS = "organization:manage_members"
    ORG_MANAGE_ROLES = "organization:manage_roles"
    ORG_DELETE = "organization:delete"

    AUDIT_READ = "audit:read"
    AUDIT_EXPORT = "audit:export"

    QUOTAS_READ = "quotas:read"
    QUOTAS_UPDATE = "quotas:update"

    API_KEYS_READ = "api_keys:read"
    API_KEYS_CREATE = "api_keys:create"
    API_KEYS_REVOKE = "api_keys:revoke"

    ALL = "*"


SYSTEM_ROLES: dict[str, dict[str, Any]] = {
    "owner": {
        "display_name": "Owner",
        "description": "Full access to all resources and organization management",
        "permissions": ["*"],
        "priority": 100,
    },
    "admin": {
        "display_name": "Administrator",
        "description": "Manage members, settings, and all resources",
        "permissions": [
            "assistants:*",
            "threads:*",
            "runs:*",
            "store:*",
            "crons:*",
            "organization:read",
            "organization:update",
            "organization:manage_members",
            "audit:read",
            "audit:export",
            "quotas:read",
            "quotas:update",
            "api_keys:*",
        ],
        "priority": 80,
    },
    "developer": {
        "display_name": "Developer",
        "description": "Create and manage AI agents and workflows",
        "permissions": [
            "assistants:*",
            "threads:*",
            "runs:*",
            "store:read",
            "store:write",
            "crons:*",
            "organization:read",
            "quotas:read",
        ],
        "priority": 60,
    },
    "viewer": {
        "display_name": "Viewer",
        "description": "Read-only access to resources",
        "permissions": [
            "assistants:read",
            "threads:read",
            "runs:read",
            "store:read",
            "crons:read",
            "organization:read",
            "quotas:read",
        ],
        "priority": 20,
    },
    "api_user": {
        "display_name": "API User",
        "description": "Limited API access for automated systems",
        "permissions": [
            "assistants:read",
            "threads:read",
            "threads:write",
            "runs:read",
            "runs:create",
            "store:read",
            "store:write",
        ],
        "priority": 40,
    },
}


class RoleDefinition(BaseModel):
    """Role with permissions. System roles (is_system=True) are immutable."""

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
    """Create a custom role (organization-specific, modifiable/deletable)."""

    name: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z_][a-z0-9_]*$")
    display_name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=99)


class RoleUpdate(BaseModel):
    """Update a custom role. System roles cannot be updated."""

    display_name: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = None
    priority: int | None = Field(default=None, ge=0, le=99)


class RoleListResponse(BaseModel):
    roles: list[RoleDefinition]
    total: int


class UserPermissionGrant(BaseModel):
    """Grant/deny custom permissions. Denials override grants (including wildcards)."""

    granted_permissions: list[str] = Field(default_factory=list)
    denied_permissions: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    reason: str | None = Field(default=None, max_length=500)


class UserCustomPermissions(BaseModel):
    """User's custom permission overrides stored in DB."""

    id: str
    user_id: str
    org_id: str
    granted_permissions: list[str] = Field(default_factory=list)
    denied_permissions: list[str] = Field(default_factory=list)
    granted_by: str | None = None
    granted_at: datetime
    expires_at: datetime | None = None
    reason: str | None = None

    model_config = {"from_attributes": True}


class UserEffectivePermissions(BaseModel):
    """Resolved permissions: role_perms + custom_granted - custom_denied."""

    user_id: str
    org_id: str
    role: str
    role_permissions: list[str]
    custom_granted: list[str]
    custom_denied: list[str]
    effective_permissions: list[str]
    resolved_at: datetime


class PermissionCheckRequest(BaseModel):
    """Check if user has a specific permission."""

    permission: str
    resource_id: str | None = None


class PermissionCheckResponse(BaseModel):
    allowed: bool
    permission: str
    reason: str | None = None
    checked_at: datetime | None = None


class BulkPermissionCheckRequest(BaseModel):
    permissions: list[str] = Field(..., min_length=1, max_length=50)


class BulkPermissionCheckResponse(BaseModel):
    results: dict[str, bool]
    all_allowed: bool


class RoleAssignment(BaseModel):
    user_id: str
    role: str


class RoleAssignmentResponse(BaseModel):
    user_id: str
    org_id: str
    previous_role: str | None
    new_role: str
    assigned_by: str
    assigned_at: datetime


__all__ = [
    "Permission",
    "SYSTEM_ROLES",
    "RoleDefinition",
    "RoleCreate",
    "RoleUpdate",
    "RoleListResponse",
    "UserPermissionGrant",
    "UserCustomPermissions",
    "UserEffectivePermissions",
    "PermissionCheckRequest",
    "PermissionCheckResponse",
    "BulkPermissionCheckRequest",
    "BulkPermissionCheckResponse",
    "RoleAssignment",
    "RoleAssignmentResponse",
]
