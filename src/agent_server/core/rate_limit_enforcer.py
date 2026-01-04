"""DB-Controlled Rate Limit Enforcer with Sliding Window Algorithm

This module provides accurate rate limiting using Redis sorted sets for
sliding window counting. It integrates with RateLimitRuleService for
DB-controlled rules while maintaining backward compatibility with the
existing env-var based rate_limiter.py.

Key Features:
- Sliding window algorithm using Redis ZADD (accurate counting)
- Priority-based rule resolution from database
- Burst limit support (secondary shorter window)
- FastAPI dependency for endpoint protection
- Graceful degradation when Redis unavailable

Algorithm:
    Sliding window uses Redis sorted sets where:
    - Members: unique request IDs (timestamp-based)
    - Scores: request timestamps (Unix ms)
    - ZREMRANGEBYSCORE removes entries outside window
    - ZCARD counts remaining entries

Usage:
    # As FastAPI dependency
    @router.post("/runs")
    async def create_run(
        _: bool = Depends(RateLimitCheck()),
        ...
    ):
        pass

    # Direct usage
    enforcer = get_rate_limit_enforcer()
    result = await enforcer.check_rate_limit(org_id, endpoint, user_id)
    if not result.allowed:
        raise HTTPException(429, detail=result.model_dump())
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .cache import cache_manager
from .orm import get_session

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Redis key prefix for rate limit counters
RATE_LIMIT_KEY_PREFIX = "rl_sw"  # rl_sw = rate limit sliding window

# Lua script for atomic sliding window check
# This script:
# 1. Removes entries outside the window (ZREMRANGEBYSCORE)
# 2. Counts remaining entries (ZCARD)
# 3. If under limit, adds new entry (ZADD)
# Returns: [current_count, was_added (0 or 1)]
SLIDING_WINDOW_CHECK_SCRIPT = """
local key = KEYS[1]
local window_start = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

-- Remove entries outside the window
redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

-- Count current entries
local count = redis.call('ZCARD', key)

-- Check if under limit and add if allowed
if count < limit then
    redis.call('ZADD', key, now, member)
    -- Set expiry to window size + buffer
    redis.call('EXPIRE', key, ARGV[5])
    return {count + 1, 1}
else
    return {count, 0}
end
"""


# =============================================================================
# Rate Limit Enforcer
# =============================================================================


class RateLimitEnforcer:
    """Enforces rate limits using sliding window algorithm.

    This enforcer:
    1. Resolves applicable rules from database via RateLimitRuleService
    2. Checks current count using Redis sorted sets (sliding window)
    3. Records check results for analytics
    4. Returns detailed result for response headers

    Thread-safe: Uses Redis for distributed counting.
    """

    def __init__(self) -> None:
        self._script: Any = None  # Registered Lua script
        self._script_registered = False
        self._fail_open = True  # Allow requests if Redis unavailable

    async def _ensure_script_registered(self) -> bool:
        """Register Lua script with Redis if not already done."""
        if self._script_registered:
            return True

        if not cache_manager.is_available:
            return False

        try:
            client = cache_manager._client
            if client:
                self._script = client.register_script(SLIDING_WINDOW_CHECK_SCRIPT)
                self._script_registered = True
                logger.debug("Registered sliding window Lua script")
                return True
        except Exception as e:
            logger.warning(f"Failed to register Lua script: {e}")

        return False

    def _build_redis_key(
        self,
        rule_id: str,
        org_id: str,
        endpoint: str | None = None,
        user_id: str | None = None,
        api_key_id: str | None = None,
    ) -> str:
        """Build Redis key for rate limit counter.

        Key format: rl_sw:{rule_id}:{org_id}:{target_qualifier}

        The target_qualifier depends on what the rule targets:
        - global/org: just org_id
        - user: user_id
        - api_key: api_key_id
        - endpoint: hashed endpoint pattern
        """
        parts = [RATE_LIMIT_KEY_PREFIX, rule_id, org_id]

        if user_id:
            parts.append(f"u:{user_id}")
        elif api_key_id:
            parts.append(f"k:{api_key_id}")
        elif endpoint:
            # Use endpoint directly (safe since fnmatch already matched)
            parts.append(f"e:{endpoint}")

        return ":".join(parts)

    async def _sliding_window_check(
        self,
        key: str,
        window_seconds: int,
        limit: int,
    ) -> tuple[int, bool]:
        """Check rate limit using sliding window algorithm.

        Args:
            key: Redis key for this rate limit counter
            window_seconds: Window size in seconds
            limit: Maximum requests allowed

        Returns:
            (current_count, was_allowed) tuple
        """
        if not cache_manager.is_available:
            if self._fail_open:
                return (0, True)
            return (limit, False)

        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (window_seconds * 1000)
        member = f"{now_ms}:{uuid.uuid4().hex[:8]}"
        expire_seconds = window_seconds + 60  # Buffer for cleanup

        try:
            # Try using Lua script for atomic operation
            if await self._ensure_script_registered() and self._script:
                result = await self._script(
                    keys=[key],
                    args=[window_start_ms, now_ms, limit, member, expire_seconds],
                )
                return (int(result[0]), bool(result[1]))

            # Fallback: Non-atomic but functional
            client = cache_manager._client
            if not client:
                return (0, True) if self._fail_open else (limit, False)

            # Remove old entries
            await client.zremrangebyscore(key, "-inf", window_start_ms)

            # Count current
            count = await client.zcard(key)

            # Check and add if allowed
            if count < limit:
                await client.zadd(key, {member: now_ms})
                await client.expire(key, expire_seconds)
                return (count + 1, True)
            else:
                return (count, False)

        except Exception as e:
            logger.error(f"Sliding window check failed: {e}")
            if self._fail_open:
                return (0, True)
            return (limit, False)

    async def _check_burst_limit(
        self,
        key: str,
        burst_limit: int,
        burst_window_seconds: int,
    ) -> tuple[int, bool, int]:
        """Check burst limit (short window).

        Returns:
            (current_count, allowed, remaining)
        """
        burst_key = f"{key}:burst"
        count, allowed = await self._sliding_window_check(burst_key, burst_window_seconds, burst_limit)
        remaining = max(0, burst_limit - count)
        return (count, allowed, remaining)

    async def check_rate_limit(
        self,
        org_id: str,
        endpoint: str,
        session: AsyncSession,
        user_id: str | None = None,
        api_key_id: str | None = None,
        ip_address: str | None = None,
    ) -> Any:  # Returns RateLimitCheckResult
        """Check if request is allowed under rate limit rules.

        Args:
            org_id: Organization ID
            endpoint: Request endpoint path
            session: Database session for rule lookup
            user_id: Optional user ID
            api_key_id: Optional API key ID
            ip_address: Optional client IP (for logging)

        Returns:
            RateLimitCheckResult with allowed status and limit info
        """
        # Import here to avoid circular imports
        from ..models.rate_limit_rules import (
            RateLimitAction,
            RateLimitCheckResult,
        )
        from ..services.rate_limit_rule_service import RateLimitRuleService

        now = datetime.now(UTC)

        # 1. Resolve applicable rule from database
        rule_service = RateLimitRuleService(session)
        matched_rule = await rule_service.resolve_rule(
            org_id=org_id,
            endpoint=endpoint,
            user_id=user_id,
            api_key_id=api_key_id,
        )

        # No rule matched - allow by default
        if matched_rule is None:
            return RateLimitCheckResult(
                allowed=True,
                matched_rule=None,
                current_count=0,
                limit=0,  # No limit
                remaining=0,
                reset_at=now + timedelta(hours=1),
                retry_after=None,
                burst_remaining=None,
            )

        # 2. Build Redis key for this rule + context
        redis_key = self._build_redis_key(
            rule_id=matched_rule.rule_id,
            org_id=org_id,
            endpoint=endpoint if matched_rule.target_type.value == "endpoint" else None,
            user_id=user_id if matched_rule.target_type.value == "user" else None,
            api_key_id=api_key_id if matched_rule.target_type.value == "api_key" else None,
        )

        # 3. Check main window
        current_count, main_allowed = await self._sliding_window_check(
            key=redis_key,
            window_seconds=matched_rule.window_seconds,
            limit=matched_rule.requests_per_window,
        )

        # 4. Check burst limit if configured
        burst_remaining: int | None = None
        burst_allowed = True

        if matched_rule.burst_limit and matched_rule.burst_window_seconds:
            _, burst_allowed, burst_remaining = await self._check_burst_limit(
                key=redis_key,
                burst_limit=matched_rule.burst_limit,
                burst_window_seconds=matched_rule.burst_window_seconds,
            )

        # 5. Determine final result
        allowed = main_allowed and burst_allowed
        remaining = max(0, matched_rule.requests_per_window - current_count)
        reset_at = now + timedelta(seconds=matched_rule.window_seconds)

        # Calculate retry_after if blocked
        retry_after: int | None = None
        if not allowed:
            # Estimate when a slot will open (rough approximation)
            retry_after = min(matched_rule.window_seconds, 60)  # Cap at 60s

        # 6. Handle action type
        action_taken: str | None = None
        if not allowed:
            if matched_rule.action == RateLimitAction.REJECT:
                action_taken = "rejected"
            elif matched_rule.action == RateLimitAction.THROTTLE:
                action_taken = "throttled"
                # For throttle, we still allow but with delay
                # Note: Actual delay would be implemented at middleware level
                allowed = True
            elif matched_rule.action == RateLimitAction.LOG_ONLY:
                action_taken = "logged"
                allowed = True

        # 7. Record check for analytics (fire and forget)
        try:
            await rule_service.record_check(
                org_id=org_id,
                rule_id=matched_rule.rule_id,
                rule_name=matched_rule.rule_name,
                allowed=allowed,
                current_count=current_count,
                limit_value=matched_rule.requests_per_window,
                user_id=user_id,
                api_key_id=api_key_id,
                endpoint=endpoint,
                action_taken=action_taken,
                ip_address=ip_address,
            )
        except Exception as e:
            logger.warning(f"Failed to record rate limit check: {e}")

        return RateLimitCheckResult(
            allowed=allowed,
            matched_rule=matched_rule,
            current_count=current_count,
            limit=matched_rule.requests_per_window,
            remaining=remaining,
            reset_at=reset_at,
            retry_after=retry_after,
            burst_remaining=burst_remaining,
        )

    async def get_current_usage(
        self,
        org_id: str,
        rule_id: str,
        window_seconds: int,
        endpoint: str | None = None,
        user_id: str | None = None,
        api_key_id: str | None = None,
    ) -> int:
        """Get current usage count for a rule without incrementing.

        Useful for analytics and status endpoints.
        """
        key = self._build_redis_key(
            rule_id=rule_id,
            org_id=org_id,
            endpoint=endpoint,
            user_id=user_id,
            api_key_id=api_key_id,
        )

        if not cache_manager.is_available:
            return 0

        try:
            client = cache_manager._client
            if not client:
                return 0

            now_ms = int(time.time() * 1000)
            window_start_ms = now_ms - (window_seconds * 1000)

            # Remove old and count
            await client.zremrangebyscore(key, "-inf", window_start_ms)
            return await client.zcard(key) or 0

        except Exception as e:
            logger.error(f"Failed to get usage count: {e}")
            return 0

    async def reset_counter(
        self,
        org_id: str,
        rule_id: str,
        endpoint: str | None = None,
        user_id: str | None = None,
        api_key_id: str | None = None,
    ) -> bool:
        """Reset rate limit counter for a specific rule/target.

        Useful for admin operations or testing.
        """
        key = self._build_redis_key(
            rule_id=rule_id,
            org_id=org_id,
            endpoint=endpoint,
            user_id=user_id,
            api_key_id=api_key_id,
        )

        return await cache_manager.delete(key)


# =============================================================================
# FastAPI Dependency
# =============================================================================


class RateLimitCheck:
    """FastAPI dependency for rate limit enforcement.

    Usage:
        @router.post("/runs")
        async def create_run(
            _: bool = Depends(RateLimitCheck()),
            ...
        ):
            pass

        # Or with endpoint override
        @router.post("/runs/stream")
        async def stream_run(
            _: bool = Depends(RateLimitCheck(endpoint_override="/runs/*")),
            ...
        ):
            pass
    """

    def __init__(
        self,
        endpoint_override: str | None = None,
        fail_open: bool = True,
    ) -> None:
        """Initialize rate limit check dependency.

        Args:
            endpoint_override: Override endpoint pattern for matching
            fail_open: If True, allow requests when Redis is unavailable
        """
        self.endpoint_override = endpoint_override
        self.fail_open = fail_open

    async def __call__(
        self,
        request: Request,
        session: AsyncSession = Depends(get_session),
    ) -> bool:
        """Check rate limit for the request.

        Extracts context from request and checks against rules.
        Sets rate limit headers on response.
        Raises HTTPException(429) if rate limited.
        """
        # Extract user context
        user = getattr(request.state, "user", None)
        if not user:
            # No user context - skip rate limiting for unauthenticated requests
            # (or handle with IP-based limiting if needed)
            return True

        org_id = getattr(user, "org_id", None)
        if not org_id:
            # No org context - skip DB-controlled rate limiting
            # Fall back to env-var based limiting in middleware
            return True

        user_id = getattr(user, "identity", None)
        api_key_id = getattr(user, "api_key_id", None)

        # Determine endpoint
        endpoint = self.endpoint_override or request.url.path

        # Get client IP
        ip_address = _get_client_ip(request)

        # Check rate limit
        enforcer = get_rate_limit_enforcer()
        result = await enforcer.check_rate_limit(
            org_id=org_id,
            endpoint=endpoint,
            session=session,
            user_id=user_id,
            api_key_id=api_key_id,
            ip_address=ip_address,
        )

        # Set rate limit headers for response
        # These will be picked up by middleware or set directly
        request.state.rate_limit_result = result

        if not result.allowed:
            headers = {
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": str(result.remaining),
                "X-RateLimit-Reset": str(int(result.reset_at.timestamp())),
            }
            if result.retry_after:
                headers["Retry-After"] = str(result.retry_after)

            rule_name = None
            if result.matched_rule:
                rule_name = result.matched_rule.rule_name

            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": "Too many requests",
                    "limit": result.limit,
                    "remaining": result.remaining,
                    "reset_at": result.reset_at.isoformat(),
                    "retry_after": result.retry_after,
                    "rule_name": rule_name,
                },
                headers=headers,
            )

        return True


def _get_client_ip(request: Request) -> str | None:
    """Extract client IP from request, handling proxies."""
    try:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take last IP (what our load balancer added)
            ips = forwarded_for.split(",")
            for ip in reversed(ips):
                cleaned = ip.strip()
                if cleaned:
                    return cleaned

        client = getattr(request, "client", None)
        if client and client.host:
            return client.host

    except Exception:
        pass

    return None


# =============================================================================
# Singleton Instance
# =============================================================================

_rate_limit_enforcer: RateLimitEnforcer | None = None


def get_rate_limit_enforcer() -> RateLimitEnforcer:
    """Get singleton rate limit enforcer instance."""
    global _rate_limit_enforcer
    if _rate_limit_enforcer is None:
        _rate_limit_enforcer = RateLimitEnforcer()
    return _rate_limit_enforcer


# =============================================================================
# Middleware Integration Helper
# =============================================================================


async def add_rate_limit_headers(request: Request, response: Any) -> None:
    """Add rate limit headers to response.

    Call this in middleware after endpoint returns.
    """
    result = getattr(request.state, "rate_limit_result", None)
    if result and result.matched_rule:
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(result.reset_at.timestamp()))

        if result.burst_remaining is not None:
            response.headers["X-RateLimit-Burst-Remaining"] = str(result.burst_remaining)


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "RateLimitEnforcer",
    "RateLimitCheck",
    "get_rate_limit_enforcer",
    "add_rate_limit_headers",
]
