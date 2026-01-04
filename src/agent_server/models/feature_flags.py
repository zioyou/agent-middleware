"""Feature Flags - Dynamic Feature Toggle System

This module defines Pydantic models for feature flag management.
Feature flags enable:
- Gradual feature rollout (percentage-based)
- A/B testing
- Kill switches for instant disable
- Per-org/per-user feature overrides

Key Concepts:
- FeatureFlag: Global flag definition with default value
- FeatureFlagOverride: Per-org/user override of a global flag
- Percentage Rollout: Consistent hashing for gradual feature release
- Flag Evaluation: Runtime evaluation considering all overrides

Resolution Order (first match wins):
1. User-specific override
2. Organization override
3. Global flag default
4. System default (disabled)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

# =============================================================================
# Enums
# =============================================================================


class FlagValueType(str, Enum):
    """Value type for feature flags.

    Determines how the flag value is interpreted and validated.
    """

    BOOLEAN = "boolean"  # True/False toggle
    STRING = "string"  # String value (e.g., variant name)
    NUMBER = "number"  # Numeric value (int or float)
    JSON = "json"  # Arbitrary JSON object


class FlagStatus(str, Enum):
    """Status of a feature flag."""

    ACTIVE = "active"  # Flag is active and being evaluated
    DISABLED = "disabled"  # Flag is disabled (returns default/off)
    ARCHIVED = "archived"  # Flag is archived (soft deleted)


class RolloutStrategy(str, Enum):
    """Strategy for percentage-based rollout.

    RANDOM: Random selection based on percentage
    USER_HASH: Consistent hashing based on user_id (same user always gets same result)
    ORG_HASH: Consistent hashing based on org_id (same org always gets same result)
    """

    RANDOM = "random"
    USER_HASH = "user_hash"
    ORG_HASH = "org_hash"


class OverrideScope(str, Enum):
    """Scope for feature flag overrides."""

    GLOBAL = "global"  # System-wide default
    ORG = "org"  # Organization-level override
    USER = "user"  # User-level override


# =============================================================================
# Percentage Rollout Models
# =============================================================================


class PercentageRolloutConfig(BaseModel):
    """Configuration for percentage-based rollout.

    Enables gradual feature release to a subset of users/orgs.
    Uses consistent hashing to ensure the same entity always
    gets the same result (no flip-flopping).
    """

    enabled: bool = Field(
        default=False,
        description="Whether percentage rollout is enabled",
    )
    percentage: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Percentage of entities to enable flag for (0-100)",
    )
    strategy: RolloutStrategy = Field(
        default=RolloutStrategy.USER_HASH,
        description="Strategy for determining which entities get the flag",
    )
    seed: str | None = Field(
        default=None,
        description="Optional seed for hash consistency across deployments",
    )


class TargetingRule(BaseModel):
    """Rule for targeting specific users or segments.

    Allows fine-grained control over who sees a feature.
    """

    attribute: str = Field(
        ...,
        description="User/org attribute to match (e.g., 'email', 'plan', 'region')",
    )
    operator: str = Field(
        ...,
        description="Comparison operator: 'eq', 'neq', 'contains', 'starts_with', 'ends_with', 'in', 'not_in', 'regex'",
    )
    value: Any = Field(
        ...,
        description="Value to compare against",
    )


class TargetingConfig(BaseModel):
    """Configuration for user/org targeting.

    Defines rules that determine which entities see the feature.
    Rules are evaluated in order; first match wins.
    """

    rules: list[TargetingRule] = Field(
        default_factory=list,
        description="List of targeting rules (evaluated in order)",
    )
    match_all: bool = Field(
        default=False,
        description="If True, all rules must match. If False, any rule match is sufficient.",
    )


# =============================================================================
# Feature Flag Models
# =============================================================================


class FeatureFlagBase(BaseModel):
    """Base fields for feature flags."""

    key: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_-]*$",
        description="Unique flag key (lowercase, alphanumeric, underscores, hyphens)",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Human-readable flag name",
    )
    description: str | None = Field(
        default=None,
        max_length=1024,
        description="Flag description explaining purpose and usage",
    )
    value_type: FlagValueType = Field(
        default=FlagValueType.BOOLEAN,
        description="Type of value this flag returns",
    )
    default_value: Any = Field(
        default=False,
        description="Default value when flag is off or no override matches",
    )
    enabled_value: Any = Field(
        default=True,
        description="Value returned when flag is enabled",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for categorization and filtering",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )

    @model_validator(mode="after")
    def validate_value_types(self) -> "FeatureFlagBase":
        """Validate that values match the declared value_type."""
        if self.value_type == FlagValueType.BOOLEAN:
            if not isinstance(self.default_value, bool):
                self.default_value = bool(self.default_value)
            if not isinstance(self.enabled_value, bool):
                self.enabled_value = bool(self.enabled_value)
        elif self.value_type == FlagValueType.NUMBER:
            if not isinstance(self.default_value, (int, float)):
                raise ValueError("default_value must be a number for NUMBER type")
            if not isinstance(self.enabled_value, (int, float)):
                raise ValueError("enabled_value must be a number for NUMBER type")
        elif self.value_type == FlagValueType.STRING:
            if not isinstance(self.default_value, str):
                self.default_value = str(self.default_value)
            if not isinstance(self.enabled_value, str):
                self.enabled_value = str(self.enabled_value)
        # JSON type accepts any value
        return self


class FeatureFlagCreate(FeatureFlagBase):
    """Request to create a new feature flag."""

    enabled: bool = Field(
        default=False,
        description="Whether the flag is enabled by default",
    )
    is_killswitch: bool = Field(
        default=False,
        description="If True, this is a killswitch that can instantly disable a feature",
    )
    rollout: PercentageRolloutConfig = Field(
        default_factory=PercentageRolloutConfig,
        description="Percentage rollout configuration",
    )
    targeting: TargetingConfig | None = Field(
        default=None,
        description="Targeting rules for specific users/orgs",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration time (flag auto-disables after this)",
    )


class FeatureFlagUpdate(BaseModel):
    """Request to update an existing feature flag.

    All fields are optional - only provided fields are updated.
    """

    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    default_value: Any | None = None
    enabled_value: Any | None = None
    enabled: bool | None = None
    is_killswitch: bool | None = None
    rollout: PercentageRolloutConfig | None = None
    targeting: TargetingConfig | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    expires_at: datetime | None = None
    status: FlagStatus | None = None


class FeatureFlag(FeatureFlagBase):
    """Complete feature flag entity (DB record)."""

    flag_id: str = Field(
        ...,
        description="Unique flag identifier (UUID)",
    )
    org_id: str = Field(
        ...,
        description="Organization that owns this flag (or 'global' for system flags)",
    )
    enabled: bool = Field(
        default=False,
        description="Whether the flag is currently enabled",
    )
    is_killswitch: bool = Field(
        default=False,
        description="If True, this is a killswitch",
    )
    status: FlagStatus = Field(
        default=FlagStatus.ACTIVE,
        description="Current flag status",
    )
    rollout: PercentageRolloutConfig = Field(
        default_factory=PercentageRolloutConfig,
        description="Percentage rollout configuration",
    )
    targeting: TargetingConfig | None = Field(
        default=None,
        description="Targeting rules",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration time",
    )
    created_at: datetime = Field(
        ...,
        description="Flag creation timestamp",
    )
    updated_at: datetime = Field(
        ...,
        description="Last update timestamp",
    )
    created_by: str | None = Field(
        default=None,
        description="User who created the flag",
    )
    version: int = Field(
        default=1,
        description="Version number (incremented on each update)",
    )

    model_config = {"from_attributes": True}


# =============================================================================
# Override Models
# =============================================================================


class FeatureFlagOverrideCreate(BaseModel):
    """Request to create a feature flag override."""

    flag_key: str = Field(
        ...,
        description="Key of the flag to override",
    )
    scope: OverrideScope = Field(
        ...,
        description="Scope of the override (org or user)",
    )
    target_id: str | None = Field(
        default=None,
        description="Target ID (user_id for USER scope, None for ORG scope)",
    )
    value: Any = Field(
        ...,
        description="Override value (must match flag's value_type)",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this override is active",
    )
    reason: str | None = Field(
        default=None,
        max_length=512,
        description="Reason for the override",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration time for temporary overrides",
    )

    @model_validator(mode="after")
    def validate_scope_target(self) -> "FeatureFlagOverrideCreate":
        """Validate scope and target_id consistency."""
        if self.scope == OverrideScope.USER and not self.target_id:
            raise ValueError("target_id (user_id) required for USER scope")
        if self.scope == OverrideScope.ORG and self.target_id:
            raise ValueError("target_id should be None for ORG scope (org_id comes from context)")
        return self


class FeatureFlagOverrideUpdate(BaseModel):
    """Request to update a feature flag override."""

    value: Any | None = None
    enabled: bool | None = None
    reason: str | None = None
    expires_at: datetime | None = None


class FeatureFlagOverride(BaseModel):
    """Feature flag override entity (DB record)."""

    override_id: str = Field(
        ...,
        description="Unique override identifier (UUID)",
    )
    flag_id: str = Field(
        ...,
        description="ID of the flag being overridden",
    )
    flag_key: str = Field(
        ...,
        description="Key of the flag being overridden",
    )
    org_id: str = Field(
        ...,
        description="Organization this override belongs to",
    )
    scope: OverrideScope = Field(
        ...,
        description="Scope of the override",
    )
    target_id: str | None = Field(
        default=None,
        description="Target ID for USER scope overrides",
    )
    value: Any = Field(
        ...,
        description="Override value",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this override is active",
    )
    reason: str | None = Field(
        default=None,
        description="Reason for the override",
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Optional expiration time",
    )
    created_at: datetime = Field(
        ...,
        description="Override creation timestamp",
    )
    updated_at: datetime = Field(
        ...,
        description="Last update timestamp",
    )
    created_by: str | None = Field(
        default=None,
        description="User who created the override",
    )

    model_config = {"from_attributes": True}


# =============================================================================
# Evaluation Models
# =============================================================================


class FlagEvaluationContext(BaseModel):
    """Context for evaluating a feature flag.

    Provides information about the entity requesting the flag value.
    """

    user_id: str | None = Field(
        default=None,
        description="User ID for user-level evaluation",
    )
    org_id: str | None = Field(
        default=None,
        description="Organization ID",
    )
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional attributes for targeting rule evaluation",
    )


class FlagEvaluationRequest(BaseModel):
    """Request to evaluate one or more feature flags."""

    flags: list[str] = Field(
        default_factory=list,
        description="List of flag keys to evaluate. Empty = evaluate all flags.",
    )
    context: FlagEvaluationContext = Field(
        default_factory=FlagEvaluationContext,
        description="Evaluation context",
    )


class FlagEvaluationResult(BaseModel):
    """Result of evaluating a single feature flag."""

    flag_key: str = Field(
        ...,
        description="Flag key that was evaluated",
    )
    value: Any = Field(
        ...,
        description="Evaluated value",
    )
    enabled: bool = Field(
        ...,
        description="Whether the flag is enabled for this context",
    )
    source: str = Field(
        ...,
        description="Source of the value: 'default', 'flag', 'override', 'rollout', 'targeting'",
    )
    reason: str = Field(
        ...,
        description="Human-readable reason for this value",
    )
    flag_id: str | None = Field(
        default=None,
        description="ID of the flag (if found)",
    )
    override_id: str | None = Field(
        default=None,
        description="ID of the override that was applied (if any)",
    )
    evaluated_at: datetime = Field(
        ...,
        description="Timestamp of evaluation",
    )


class FlagEvaluationResponse(BaseModel):
    """Response containing evaluated flag values."""

    flags: dict[str, FlagEvaluationResult] = Field(
        default_factory=dict,
        description="Map of flag key to evaluation result",
    )
    context: FlagEvaluationContext = Field(
        ...,
        description="Context used for evaluation",
    )
    evaluated_at: datetime = Field(
        ...,
        description="Timestamp of evaluation",
    )


# =============================================================================
# List/Search Models
# =============================================================================


class FeatureFlagListRequest(BaseModel):
    """Request to list feature flags."""

    status: FlagStatus | None = Field(
        default=None,
        description="Filter by status",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Filter by tags (OR matching)",
    )
    is_killswitch: bool | None = Field(
        default=None,
        description="Filter by killswitch flags",
    )
    search: str | None = Field(
        default=None,
        description="Search in key, name, description",
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


class FeatureFlagListResponse(BaseModel):
    """Response containing list of feature flags."""

    flags: list[FeatureFlag] = Field(
        default_factory=list,
        description="List of flags",
    )
    total: int = Field(
        ...,
        description="Total number of matching flags",
    )
    limit: int = Field(
        ...,
        description="Page size",
    )
    offset: int = Field(
        ...,
        description="Current offset",
    )


class FeatureFlagOverrideListRequest(BaseModel):
    """Request to list feature flag overrides."""

    flag_key: str | None = Field(
        default=None,
        description="Filter by flag key",
    )
    scope: OverrideScope | None = Field(
        default=None,
        description="Filter by scope",
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


class FeatureFlagOverrideListResponse(BaseModel):
    """Response containing list of feature flag overrides."""

    overrides: list[FeatureFlagOverride] = Field(
        default_factory=list,
        description="List of overrides",
    )
    total: int = Field(
        ...,
        description="Total number of matching overrides",
    )
    limit: int = Field(
        ...,
        description="Page size",
    )
    offset: int = Field(
        ...,
        description="Current offset",
    )


# =============================================================================
# Audit/History Models
# =============================================================================


class FlagChangeEvent(BaseModel):
    """Record of a change to a feature flag."""

    event_id: str = Field(..., description="Unique event ID")
    flag_id: str = Field(..., description="Flag that was changed")
    flag_key: str = Field(..., description="Flag key")
    org_id: str = Field(..., description="Organization")
    event_type: str = Field(
        ...,
        description="Type of change: 'created', 'updated', 'enabled', 'disabled', 'archived', 'override_added', 'override_removed'",
    )
    changed_by: str | None = Field(default=None, description="User who made the change")
    previous_value: Any = Field(default=None, description="Previous value/state")
    new_value: Any = Field(default=None, description="New value/state")
    timestamp: datetime = Field(..., description="When the change occurred")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional event metadata")


class FlagHistoryRequest(BaseModel):
    """Request for flag change history."""

    flag_key: str | None = Field(
        default=None,
        description="Filter by flag key",
    )
    event_type: str | None = Field(
        default=None,
        description="Filter by event type",
    )
    start_time: datetime | None = Field(
        default=None,
        description="Start of time range",
    )
    end_time: datetime | None = Field(
        default=None,
        description="End of time range",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum results",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Pagination offset",
    )


class FlagHistoryResponse(BaseModel):
    """Response containing flag change history."""

    events: list[FlagChangeEvent] = Field(
        default_factory=list,
        description="List of change events",
    )
    total: int = Field(..., description="Total matching events")
    limit: int = Field(..., description="Page size")
    offset: int = Field(..., description="Current offset")
