"""Rate Limit Rules API - DB-Controlled Rate Limiting Management

This module provides REST API endpoints for managing rate limit rules.
Rules are stored in PostgreSQL and enforced via RateLimitEnforcer.

Endpoints:
- GET  /organizations/{org_id}/rate-limits         - List rules
- POST /organizations/{org_id}/rate-limits         - Create rule
- GET  /organizations/{org_id}/rate-limits/{rule_id} - Get rule
- PATCH /organizations/{org_id}/rate-limits/{rule_id} - Update rule
- DELETE /organizations/{org_id}/rate-limits/{rule_id} - Delete rule
- GET  /organizations/{org_id}/rate-limits/usage   - Get usage stats
- POST /organizations/{org_id}/rate-limits/check   - Check rate limit

Authorization:
- Read operations: organization:read permission
- Write operations: owner or admin role
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth_deps import get_current_user
from ..core.orm import get_session
from ..core.rate_limit_enforcer import get_rate_limit_enforcer
from ..core.rbac import RequirePermission, RequireRole
from ..models.auth import User
from ..models.rate_limit_rules import (
    RateLimitCheckRequest,
    RateLimitCheckResult,
    RateLimitRule,
    RateLimitRuleCreate,
    RateLimitRuleListRequest,
    RateLimitRuleListResponse,
    RateLimitRuleUpdate,
    RateLimitRuleUsage,
    RateLimitTarget,
    RateLimitUsageResponse,
)
from ..services.rate_limit_rule_service import RateLimitRuleService

router = APIRouter(prefix="/organizations/{org_id}/rate-limits", tags=["Rate Limits"])


# =============================================================================
# List / Search Rules
# =============================================================================


@router.get("", response_model=RateLimitRuleListResponse)
async def list_rate_limit_rules(
    org_id: str,
    target_type: RateLimitTarget | None = Query(default=None, description="Filter by target type"),
    target_id: str | None = Query(default=None, description="Filter by target ID"),
    enabled: bool | None = Query(default=None, description="Filter by enabled status"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> RateLimitRuleListResponse:
    """List rate limit rules for an organization.

    Returns paginated list of rules with optional filtering.
    Rules are sorted by priority (descending), then by created_at (descending).
    """
    service = RateLimitRuleService(session)

    request = RateLimitRuleListRequest(
        target_type=target_type,
        target_id=target_id,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )

    return await service.list_rules(org_id, request)


# =============================================================================
# Create Rule
# =============================================================================


@router.post("", response_model=RateLimitRule, status_code=201)
async def create_rate_limit_rule(
    org_id: str,
    request: RateLimitRuleCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> RateLimitRule:
    """Create a new rate limit rule.

    Rule names must be unique within an organization.
    Default priority values:
    - global: 0
    - org: 100
    - endpoint: 200
    - user: 300
    - api_key: 400

    Higher priority rules take precedence when multiple rules match.
    """
    service = RateLimitRuleService(session)
    return await service.create_rule(org_id, request, user.identity)


# =============================================================================
# Get Single Rule
# =============================================================================


@router.get("/{rule_id}", response_model=RateLimitRule)
async def get_rate_limit_rule(
    org_id: str,
    rule_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> RateLimitRule:
    """Get a specific rate limit rule by ID."""
    service = RateLimitRuleService(session)
    rule = await service.get_rule(org_id, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rate limit rule '{rule_id}' not found")
    return rule


# =============================================================================
# Update Rule
# =============================================================================


@router.patch("/{rule_id}", response_model=RateLimitRule)
async def update_rate_limit_rule(
    org_id: str,
    rule_id: str,
    request: RateLimitRuleUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> RateLimitRule:
    """Update an existing rate limit rule.

    Only provided fields are updated (partial update).
    Note: Updating a rule clears its cached resolution in Redis.
    """
    service = RateLimitRuleService(session)
    return await service.update_rule(org_id, rule_id, request, user.identity)


# =============================================================================
# Delete Rule
# =============================================================================


@router.delete("/{rule_id}", status_code=204)
async def delete_rate_limit_rule(
    org_id: str,
    rule_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> None:
    """Delete a rate limit rule.

    This permanently removes the rule. Any cached resolutions are invalidated.
    Historical rate limit data (violations, checks) is retained for analytics.
    """
    service = RateLimitRuleService(session)
    await service.delete_rule(org_id, rule_id)


# =============================================================================
# Usage Statistics
# =============================================================================


@router.get("/usage", response_model=RateLimitUsageResponse)
async def get_rate_limit_usage(
    org_id: str,
    rule_id: str | None = Query(default=None, description="Get usage for specific rule"),
    user_id: str | None = Query(default=None, description="Get usage for specific user"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> RateLimitUsageResponse:
    """Get current rate limit usage statistics.

    Returns real-time usage data from Redis for active rules.
    Includes current counts, remaining capacity, and reset times.
    """
    service = RateLimitRuleService(session)
    enforcer = get_rate_limit_enforcer()

    # Get all active rules for the org
    rules_response = await service.list_rules(
        org_id,
        RateLimitRuleListRequest(enabled=True, limit=100),
    )

    usage_list: list[RateLimitRuleUsage] = []
    now = datetime.now(UTC)

    for rule in rules_response.rules:
        # Skip if filtering by rule_id and doesn't match
        if rule_id and rule.rule_id != rule_id:
            continue

        # Get current usage from Redis
        current_count = await enforcer.get_current_usage(
            org_id=org_id,
            rule_id=rule.rule_id,
            window_seconds=rule.window_size.seconds,
            user_id=user_id if rule.target_type == RateLimitTarget.USER else None,
        )

        remaining = max(0, rule.requests_per_window - current_count)
        usage_percent = (
            (current_count / rule.requests_per_window * 100) if rule.requests_per_window > 0 else 0
        )

        # Calculate reset time (approximate - based on window size)
        reset_at = now + __import__("datetime").timedelta(seconds=rule.window_size.seconds)

        usage_list.append(
            RateLimitRuleUsage(
                rule_id=rule.rule_id,
                rule_name=rule.name,
                current_count=current_count,
                limit=rule.requests_per_window,
                remaining=remaining,
                usage_percent=round(usage_percent, 2),
                reset_at=reset_at,
                violations_today=0,  # TODO: Implement violation counting
            )
        )

    return RateLimitUsageResponse(
        org_id=org_id,
        rules=usage_list,
        timestamp=now,
    )


# =============================================================================
# Check Rate Limit (Manual Check)
# =============================================================================


@router.post("/check", response_model=RateLimitCheckResult)
async def check_rate_limit(
    org_id: str,
    request: RateLimitCheckRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(RequirePermission("organization:read")),
) -> RateLimitCheckResult:
    """Check rate limit status for a specific endpoint/user/api_key combination.

    This is a dry-run check that returns the current rate limit status
    without incrementing the counter. Useful for debugging and monitoring.

    Note: This does NOT consume a request from the quota.
    """
    enforcer = get_rate_limit_enforcer()

    # For check endpoint, we want to inspect without incrementing
    # So we'll use the service directly to resolve the rule
    service = RateLimitRuleService(session)

    matched_rule = await service.resolve_rule(
        org_id=org_id,
        endpoint=request.endpoint,
        user_id=request.user_id,
        api_key_id=request.api_key_id,
    )

    now = datetime.now(UTC)

    if matched_rule is None:
        return RateLimitCheckResult(
            allowed=True,
            matched_rule=None,
            current_count=0,
            limit=0,
            remaining=0,
            reset_at=now + __import__("datetime").timedelta(hours=1),
            retry_after=None,
            burst_remaining=None,
        )

    # Get current usage without incrementing
    current_count = await enforcer.get_current_usage(
        org_id=org_id,
        rule_id=matched_rule.rule_id,
        window_seconds=matched_rule.window_seconds,
        endpoint=request.endpoint if matched_rule.target_type.value == "endpoint" else None,
        user_id=request.user_id if matched_rule.target_type.value == "user" else None,
        api_key_id=request.api_key_id if matched_rule.target_type.value == "api_key" else None,
    )

    remaining = max(0, matched_rule.requests_per_window - current_count)
    allowed = current_count < matched_rule.requests_per_window
    reset_at = now + __import__("datetime").timedelta(seconds=matched_rule.window_seconds)

    return RateLimitCheckResult(
        allowed=allowed,
        matched_rule=matched_rule,
        current_count=current_count,
        limit=matched_rule.requests_per_window,
        remaining=remaining,
        reset_at=reset_at,
        retry_after=None if allowed else min(matched_rule.window_seconds, 60),
        burst_remaining=None,  # TODO: Implement burst check
    )


# =============================================================================
# Reset Counter (Admin)
# =============================================================================


@router.post("/{rule_id}/reset", status_code=204)
async def reset_rate_limit_counter(
    org_id: str,
    rule_id: str,
    user_id: str | None = Query(default=None, description="Reset counter for specific user"),
    api_key_id: str | None = Query(default=None, description="Reset counter for specific API key"),
    endpoint: str | None = Query(default=None, description="Reset counter for specific endpoint"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    _: str = Depends(RequireRole("owner", "admin")),
) -> None:
    """Reset rate limit counter for a rule.

    This clears the current count in Redis, effectively resetting the rate limit.
    Useful for emergency situations or testing.

    Optionally specify user_id, api_key_id, or endpoint to reset a specific counter.
    """
    # Verify rule exists
    service = RateLimitRuleService(session)
    rule = await service.get_rule(org_id, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail=f"Rate limit rule '{rule_id}' not found")

    # Reset counter
    enforcer = get_rate_limit_enforcer()
    await enforcer.reset_counter(
        org_id=org_id,
        rule_id=rule_id,
        endpoint=endpoint,
        user_id=user_id,
        api_key_id=api_key_id,
    )
