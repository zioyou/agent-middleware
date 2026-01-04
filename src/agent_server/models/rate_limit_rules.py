"""Advanced Rate Limiting Rules - DB-Controlled Configuration

This module defines Pydantic models for database-controlled rate limiting rules.
Unlike the basic rate_limit.py (env var based), these models support:
- Per-org, per-user, per-endpoint configurable rules
- Rule priority and inheritance
- Multiple window sizes (second, minute, hour, day)
- Analytics and usage tracking

Key Concepts:
- RateLimitRule: Stored in DB, defines rate limit constraints
- Rule Resolution: More specific rules override general ones (priority-based)
- Sliding Window: Enforced via Redis ZADD with timestamp scores
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# =============================================================================
# Enums
# =============================================================================


class RateLimitTarget(str, Enum):
    """Target type for rate limit rule application.

    Determines what entity the rate limit applies to.
    Resolution order (most specific wins):
    1. api_key - Specific API key
    2. user - Specific user
    3. endpoint - Specific endpoint pattern
    4. org - Entire organization
    5. global - System-wide default
    """

    GLOBAL = "global"
    ORG = "org"
    USER = "user"
    API_KEY = "api_key"
    ENDPOINT = "endpoint"


class RateLimitWindow(str, Enum):
    """Time window for rate limit measurement.

    Defines the period over which requests are counted.
    """

    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"

    @property
    def seconds(self) -> int:
        """Convert window to seconds."""
        mapping = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400,
        }
        return mapping[self.value]


class RateLimitAction(str, Enum):
    """Action to take when rate limit is exceeded.

    REJECT: Return 429 Too Many Requests
    THROTTLE: Slow down requests (add delay)
    LOG_ONLY: Log violation but allow request
    """

    REJECT = "reject"
    THROTTLE = "throttle"
    LOG_ONLY = "log_only"


class RateLimitStatus(str, Enum):
    """Status of a rate limit rule."""

    ACTIVE = "active"
    DISABLED = "disabled"
    EXPIRED = "expired"


# =============================================================================
# Rate Limit Rule Models
# =============================================================================


class RateLimitRuleBase(BaseModel):
    """Base fields for rate limit rules."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Human-readable rule name",
    )
    description: str | None = Field(
        default=None,
        max_length=512,
        description="Rule description",
    )
    target_type: RateLimitTarget = Field(
        ...,
        description="What entity this rule applies to",
    )
    target_id: str | None = Field(
        default=None,
        description="Specific target ID (user_id, api_key_id, etc.). None for org/global scope.",
    )
    endpoint_pattern: str | None = Field(
        default=None,
        description="Endpoint pattern to match (e.g., '/runs/*', '/threads/*/runs'). Supports glob patterns.",
    )
    requests_per_window: int = Field(
        ...,
        ge=1,
        description="Maximum requests allowed per window",
    )
    window_size: RateLimitWindow = Field(
        default=RateLimitWindow.HOUR,
        description="Time window for counting requests",
    )
    burst_limit: int | None = Field(
        default=None,
        ge=1,
        description="Maximum burst requests (short-term spike allowance)",
    )
    burst_window: RateLimitWindow | None = Field(
        default=None,
        description="Window for burst limit (typically SECOND or MINUTE)",
    )
    action: RateLimitAction = Field(
        default=RateLimitAction.REJECT,
        description="Action when limit exceeded",
    )
    priority: int = Field(
        default=0,
        ge=0,
        le=1000,
        description="Rule priority (higher = more specific, wins conflicts). "
        "Default priorities: global=0, org=100, endpoint=200, user=300, api_key=400",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata (e.g., reason, category)",
    )

    @model_validator(mode="after")
    def validate_target_consistency(self) -> "RateLimitRuleBase":
        """Validate target_type and target_id consistency."""
        if self.target_type in (RateLimitTarget.GLOBAL, RateLimitTarget.ORG):
            # Global and org rules don't need target_id (org_id comes from context)
            pass
        elif self.target_type in (RateLimitTarget.USER, RateLimitTarget.API_KEY):
            if not self.target_id:
                raise ValueError(f"target_id required for target_type={self.target_type.value}")
        elif self.target_type == RateLimitTarget.ENDPOINT:
            if not self.endpoint_pattern:
                raise ValueError("endpoint_pattern required for target_type=endpoint")

        # Validate burst configuration
        if self.burst_limit is not None and self.burst_window is None:
            self.burst_window = RateLimitWindow.SECOND

        return self


class RateLimitRuleCreate(RateLimitRuleBase):
    """Request to create a new rate limit rule."""

    enabled: bool = Field(
        default=True,
        description="Whether the rule is active",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration time for temporary rules",
    )


class RateLimitRuleUpdate(BaseModel):
    """Request to update an existing rate limit rule.

    All fields are optional - only provided fields are updated.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    requests_per_window: int | None = Field(default=None, ge=1)
    window_size: RateLimitWindow | None = None
    burst_limit: int | None = Field(default=None, ge=1)
    burst_window: RateLimitWindow | None = None
    action: RateLimitAction | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)
    enabled: bool | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class RateLimitRule(RateLimitRuleBase):
    """Complete rate limit rule entity (DB record).

    This model represents a rate limit rule stored in the database.
    """

    rule_id: str = Field(
        ...,
        description="Unique rule identifier (UUID)",
    )
    org_id: str = Field(
        ...,
        description="Organization that owns this rule",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the rule is active",
    )
    status: RateLimitStatus = Field(
        default=RateLimitStatus.ACTIVE,
        description="Current rule status",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration time",
    )
    created_at: datetime = Field(
        ...,
        description="Rule creation timestamp",
    )
    updated_at: datetime = Field(
        ...,
        description="Last update timestamp",
    )
    created_by: str | None = Field(
        default=None,
        description="User who created the rule",
    )

    model_config = {"from_attributes": True}


# =============================================================================
# Rule Resolution Models
# =============================================================================


class RateLimitRuleMatch(BaseModel):
    """Result of resolving applicable rate limit rules for a request.

    Contains the matched rule and computed limits after considering
    priority, inheritance, and overrides.
    """

    rule_id: str = Field(
        ...,
        description="ID of the matched rule",
    )
    rule_name: str = Field(
        ...,
        description="Name of the matched rule",
    )
    target_type: RateLimitTarget = Field(
        ...,
        description="Target type of matched rule",
    )
    requests_per_window: int = Field(
        ...,
        description="Effective request limit",
    )
    window_size: RateLimitWindow = Field(
        ...,
        description="Effective window size",
    )
    window_seconds: int = Field(
        ...,
        description="Window size in seconds",
    )
    burst_limit: int | None = Field(
        default=None,
        description="Effective burst limit",
    )
    burst_window_seconds: int | None = Field(
        default=None,
        description="Burst window in seconds",
    )
    action: RateLimitAction = Field(
        ...,
        description="Action when exceeded",
    )
    priority: int = Field(
        ...,
        description="Rule priority",
    )

    @classmethod
    def from_rule(cls, rule: RateLimitRule) -> "RateLimitRuleMatch":
        """Create match result from a rule."""
        return cls(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            target_type=rule.target_type,
            requests_per_window=rule.requests_per_window,
            window_size=rule.window_size,
            window_seconds=rule.window_size.seconds,
            burst_limit=rule.burst_limit,
            burst_window_seconds=rule.burst_window.seconds if rule.burst_window else None,
            action=rule.action,
            priority=rule.priority,
        )


class RateLimitCheckRequest(BaseModel):
    """Request to check rate limit status."""

    endpoint: str = Field(
        ...,
        description="Endpoint being accessed",
    )
    user_id: str | None = Field(
        default=None,
        description="User making the request",
    )
    api_key_id: str | None = Field(
        default=None,
        description="API key used (if any)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context for rule matching",
    )


class RateLimitCheckResult(BaseModel):
    """Result of rate limit check.

    Indicates whether the request is allowed and provides
    rate limit status information.
    """

    allowed: bool = Field(
        ...,
        description="Whether the request is allowed",
    )
    matched_rule: RateLimitRuleMatch | None = Field(
        default=None,
        description="The rule that was applied (None if no rule matched)",
    )
    current_count: int = Field(
        default=0,
        description="Current request count in window",
    )
    limit: int = Field(
        ...,
        description="Maximum requests allowed",
    )
    remaining: int = Field(
        ...,
        description="Remaining requests in window",
    )
    reset_at: datetime = Field(
        ...,
        description="When the rate limit window resets",
    )
    retry_after: int | None = Field(
        default=None,
        description="Seconds to wait before retrying (if not allowed)",
    )
    burst_remaining: int | None = Field(
        default=None,
        description="Remaining burst requests",
    )


# =============================================================================
# Analytics Models
# =============================================================================


class RateLimitHit(BaseModel):
    """Record of a rate limit check (for analytics)."""

    rule_id: str = Field(..., description="Rule that was checked")
    org_id: str = Field(..., description="Organization")
    timestamp: datetime = Field(..., description="When the check occurred")
    allowed: bool = Field(..., description="Whether request was allowed")
    user_id: str | None = Field(default=None, description="User if applicable")
    endpoint: str | None = Field(default=None, description="Endpoint accessed")
    current_count: int = Field(..., description="Count at time of check")
    limit: int = Field(..., description="Limit at time of check")


class RateLimitViolation(BaseModel):
    """Record of a rate limit violation."""

    rule_id: str = Field(..., description="Rule that was violated")
    org_id: str = Field(..., description="Organization")
    timestamp: datetime = Field(..., description="When violation occurred")
    user_id: str | None = Field(default=None, description="User if applicable")
    api_key_id: str | None = Field(default=None, description="API key if applicable")
    endpoint: str = Field(..., description="Endpoint that was blocked")
    current_count: int = Field(..., description="Count at violation")
    limit: int = Field(..., description="Limit that was exceeded")
    action_taken: RateLimitAction = Field(..., description="Action that was taken")


class RateLimitAnalytics(BaseModel):
    """Aggregated rate limit analytics for a rule or organization."""

    rule_id: str | None = Field(default=None, description="Rule ID (None for org-wide)")
    org_id: str = Field(..., description="Organization")
    period_start: datetime = Field(..., description="Analytics period start")
    period_end: datetime = Field(..., description="Analytics period end")
    total_checks: int = Field(default=0, description="Total rate limit checks")
    total_allowed: int = Field(default=0, description="Total allowed requests")
    total_blocked: int = Field(default=0, description="Total blocked requests")
    unique_users: int = Field(default=0, description="Unique users affected")
    peak_usage: int = Field(default=0, description="Peak usage in period")
    peak_timestamp: datetime | None = Field(default=None, description="When peak occurred")
    avg_usage_percent: float = Field(default=0.0, description="Average usage as % of limit")


# =============================================================================
# List/Search Models
# =============================================================================


class RateLimitRuleListRequest(BaseModel):
    """Request to list rate limit rules."""

    target_type: RateLimitTarget | None = Field(
        default=None,
        description="Filter by target type",
    )
    target_id: str | None = Field(
        default=None,
        description="Filter by target ID",
    )
    enabled: bool | None = Field(
        default=None,
        description="Filter by enabled status",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum results to return",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Pagination offset",
    )


class RateLimitRuleListResponse(BaseModel):
    """Response containing list of rate limit rules."""

    rules: list[RateLimitRule] = Field(
        default_factory=list,
        description="List of rules",
    )
    total: int = Field(
        ...,
        description="Total number of matching rules",
    )
    limit: int = Field(
        ...,
        description="Page size",
    )
    offset: int = Field(
        ...,
        description="Current offset",
    )


class RateLimitUsageRequest(BaseModel):
    """Request for rate limit usage statistics."""

    rule_id: str | None = Field(
        default=None,
        description="Get usage for specific rule",
    )
    user_id: str | None = Field(
        default=None,
        description="Get usage for specific user",
    )
    window: RateLimitWindow = Field(
        default=RateLimitWindow.HOUR,
        description="Time window for usage stats",
    )


class RateLimitUsageResponse(BaseModel):
    """Response containing rate limit usage statistics."""

    org_id: str = Field(..., description="Organization")
    rules: list[RateLimitRuleUsage] = Field(
        default_factory=list,
        description="Usage per rule",
    )
    timestamp: datetime = Field(..., description="When stats were collected")


class RateLimitRuleUsage(BaseModel):
    """Usage statistics for a single rule."""

    rule_id: str = Field(..., description="Rule ID")
    rule_name: str = Field(..., description="Rule name")
    current_count: int = Field(..., description="Current count in window")
    limit: int = Field(..., description="Maximum limit")
    remaining: int = Field(..., description="Remaining requests")
    usage_percent: float = Field(..., description="Usage as percentage")
    reset_at: datetime = Field(..., description="When window resets")
    violations_today: int = Field(default=0, description="Violations in last 24h")
