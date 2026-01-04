"""Feature Flags API - Dynamic Feature Toggle Management

This module provides REST API endpoints for managing feature flags.
Flags are stored in PostgreSQL and evaluated with Redis caching.

Endpoints:
- GET  /organizations/{org_id}/feature-flags               - List flags
- POST /organizations/{org_id}/feature-flags               - Create flag
- GET  /organizations/{org_id}/feature-flags/{flag_id}     - Get flag
- GET  /organizations/{org_id}/feature-flags/key/{key}     - Get flag by key
- PATCH /organizations/{org_id}/feature-flags/{flag_id}    - Update flag
- DELETE /organizations/{org_id}/feature-flags/{flag_id}   - Delete flag
- GET  /organizations/{org_id}/feature-flags/overrides     - List overrides
- POST /organizations/{org_id}/feature-flags/overrides     - Create override
- PATCH /organizations/{org_id}/feature-flags/overrides/{override_id} - Update override
- DELETE /organizations/{org_id}/feature-flags/overrides/{override_id} - Delete override
- POST /organizations/{org_id}/feature-flags/evaluate      - Evaluate flags
- GET  /organizations/{org_id}/feature-flags/{flag_key}/evaluate - Evaluate single flag
- GET  /organizations/{org_id}/feature-flags/history       - Get change history

Authorization:
- Read operations: organization:read permission
- Write operations: owner or admin role
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth_deps import get_current_user
from ..core.orm import get_session
from ..core.rbac import RequirePermission, RequireRole
from ..models.auth import User
from ..models.feature_flags import (
    FeatureFlag,
    FeatureFlagCreate,
    FeatureFlagListRequest,
    FeatureFlagListResponse,
    FeatureFlagOverride,
    FeatureFlagOverrideCreate,
    FeatureFlagOverrideListRequest,
    FeatureFlagOverrideListResponse,
    FeatureFlagOverrideUpdate,
    FeatureFlagUpdate,
    FlagEvaluationContext,
    FlagEvaluationRequest,
    FlagEvaluationResponse,
    FlagEvaluationResult,
    FlagHistoryRequest,
    FlagHistoryResponse,
    FlagStatus,
    OverrideScope,
)
from ..services.feature_flag_service import FeatureFlagService

router = APIRouter(prefix="/organizations/{org_id}/feature-flags", tags=["Feature Flags"])


# =============================================================================
# List / Search Flags
# =============================================================================


@router.get("", response_model=FeatureFlagListResponse)
async def list_feature_flags(
    org_id: str,
    status: FlagStatus | None = Query(default=None, description="Filter by status"),
    tags: list[str] | None = Query(default=None, description="Filter by tags"),
    is_killswitch: bool | None = Query(default=None, description="Filter by killswitch"),
    search: str | None = Query(default=None, description="Search in key, name, description"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> FeatureFlagListResponse:
    """List feature flags for an organization.

    Returns paginated list of flags with optional filtering.
    Flags are sorted by created_at (descending).
    """
    service = FeatureFlagService(session)

    request = FeatureFlagListRequest(
        status=status,
        tags=tags,
        is_killswitch=is_killswitch,
        search=search,
        limit=limit,
        offset=offset,
    )

    return await service.list_flags(org_id, request)


# =============================================================================
# Create Flag
# =============================================================================


@router.post("", response_model=FeatureFlag, status_code=201)
async def create_feature_flag(
    org_id: str,
    request: FeatureFlagCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> FeatureFlag:
    """Create a new feature flag.

    Flag keys must be unique within an organization.
    Keys must be lowercase, alphanumeric with underscores/hyphens.

    Rollout configuration:
    - enabled: Whether rollout is active
    - percentage: 0-100, percentage of users/orgs to enable
    - strategy: random, user_hash (consistent per user), org_hash (consistent per org)
    """
    service = FeatureFlagService(session)
    return await service.create_flag(org_id, request, user.identity)


# =============================================================================
# Get Single Flag
# =============================================================================


@router.get("/{flag_id}", response_model=FeatureFlag)
async def get_feature_flag(
    org_id: str,
    flag_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> FeatureFlag:
    """Get a specific feature flag by ID."""
    service = FeatureFlagService(session)
    flag = await service.get_flag(org_id, flag_id)
    if not flag:
        raise HTTPException(status_code=404, detail=f"Feature flag '{flag_id}' not found")
    return flag


@router.get("/key/{key}", response_model=FeatureFlag)
async def get_feature_flag_by_key(
    org_id: str,
    key: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> FeatureFlag:
    """Get a specific feature flag by key."""
    service = FeatureFlagService(session)
    flag = await service.get_flag_by_key(org_id, key)
    if not flag:
        raise HTTPException(status_code=404, detail=f"Feature flag with key '{key}' not found")
    return flag


# =============================================================================
# Update Flag
# =============================================================================


@router.patch("/{flag_id}", response_model=FeatureFlag)
async def update_feature_flag(
    org_id: str,
    flag_id: str,
    request: FeatureFlagUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> FeatureFlag:
    """Update an existing feature flag.

    Only provided fields are updated (partial update).
    Each update increments the version number.
    Changes are logged in the change history for audit.
    """
    service = FeatureFlagService(session)
    return await service.update_flag(org_id, flag_id, request, user.identity)


# =============================================================================
# Delete Flag
# =============================================================================


@router.delete("/{flag_id}", status_code=204)
async def delete_feature_flag(
    org_id: str,
    flag_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> None:
    """Delete a feature flag.

    This permanently removes the flag and all its overrides.
    Change history is retained for audit purposes.
    Consider archiving the flag instead of deleting.
    """
    service = FeatureFlagService(session)
    await service.delete_flag(org_id, flag_id, user.identity)


# =============================================================================
# Override Management
# =============================================================================


@router.get("/overrides", response_model=FeatureFlagOverrideListResponse)
async def list_feature_flag_overrides(
    org_id: str,
    flag_key: str | None = Query(default=None, description="Filter by flag key"),
    scope: OverrideScope | None = Query(default=None, description="Filter by scope"),
    target_id: str | None = Query(default=None, description="Filter by target ID"),
    enabled: bool | None = Query(default=None, description="Filter by enabled status"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> FeatureFlagOverrideListResponse:
    """List feature flag overrides for an organization.

    Overrides allow per-org or per-user customization of flag values.
    Resolution order: user override > org override > global flag value.
    """
    service = FeatureFlagService(session)

    request = FeatureFlagOverrideListRequest(
        flag_key=flag_key,
        scope=scope,
        target_id=target_id,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )

    return await service.list_overrides(org_id, request)


@router.post("/overrides", response_model=FeatureFlagOverride, status_code=201)
async def create_feature_flag_override(
    org_id: str,
    request: FeatureFlagOverrideCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> FeatureFlagOverride:
    """Create a feature flag override.

    Overrides can be scoped to:
    - ORG: Override for the entire organization (target_id = None)
    - USER: Override for a specific user (target_id = user_id)

    The value must match the flag's value_type.
    """
    service = FeatureFlagService(session)
    return await service.create_override(org_id, request, user.identity)


@router.patch("/overrides/{override_id}", response_model=FeatureFlagOverride)
async def update_feature_flag_override(
    org_id: str,
    override_id: str,
    request: FeatureFlagOverrideUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> FeatureFlagOverride:
    """Update an existing feature flag override.

    Only provided fields are updated (partial update).
    """
    service = FeatureFlagService(session)
    return await service.update_override(org_id, override_id, request, user.identity)


@router.delete("/overrides/{override_id}", status_code=204)
async def delete_feature_flag_override(
    org_id: str,
    override_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> None:
    """Delete a feature flag override.

    The flag will revert to its default value for the affected scope.
    """
    service = FeatureFlagService(session)
    await service.delete_override(org_id, override_id, user.identity)


# =============================================================================
# Flag Evaluation
# =============================================================================


@router.post("/evaluate", response_model=FlagEvaluationResponse)
async def evaluate_feature_flags(
    org_id: str,
    request: FlagEvaluationRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> FlagEvaluationResponse:
    """Evaluate multiple feature flags for a given context.

    If no flag keys are specified, evaluates all active flags.
    Returns the resolved value for each flag considering:
    - Flag status (active, disabled, archived)
    - Expiration time
    - User-specific overrides
    - Org-specific overrides
    - Percentage rollout

    Results are cached in Redis for performance.
    """
    service = FeatureFlagService(session)
    return await service.evaluate_flags(
        org_id,
        request.context,
        request.flags if request.flags else None,
    )


@router.get("/{flag_key}/evaluate", response_model=FlagEvaluationResult)
async def evaluate_single_flag(
    org_id: str,
    flag_key: str,
    user_id: str | None = Query(default=None, description="User ID for evaluation context"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> FlagEvaluationResult:
    """Evaluate a single feature flag by key.

    Convenience endpoint for checking a single flag.
    Use POST /evaluate for batch evaluation.
    """
    service = FeatureFlagService(session)

    context = FlagEvaluationContext(
        user_id=user_id or user.identity,
        org_id=org_id,
    )

    response = await service.evaluate_flags(org_id, context, [flag_key])

    if flag_key not in response.flags:
        raise HTTPException(
            status_code=404,
            detail=f"Feature flag with key '{flag_key}' not found",
        )

    return response.flags[flag_key]


# =============================================================================
# Change History
# =============================================================================


@router.get("/history", response_model=FlagHistoryResponse)
async def get_flag_history(
    org_id: str,
    flag_key: str | None = Query(default=None, description="Filter by flag key"),
    event_type: str | None = Query(default=None, description="Filter by event type"),
    limit: int = Query(default=50, ge=1, le=200, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> FlagHistoryResponse:
    """Get feature flag change history.

    Returns a log of all changes to flags and overrides.
    Event types include: created, updated, enabled, disabled,
    archived, override_added, override_removed, override_updated.
    """
    service = FeatureFlagService(session)

    request = FlagHistoryRequest(
        flag_key=flag_key,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )

    return await service.get_flag_history(org_id, request)
