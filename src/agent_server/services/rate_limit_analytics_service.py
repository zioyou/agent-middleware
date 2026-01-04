"""Rate Limit Analytics Service

This service provides aggregated analytics and insights from rate limit history data.
It queries the rate_limit_history table to generate:
- Usage statistics per rule, user, endpoint
- Violation counts and trends
- Peak usage analysis
- Time-series data for dashboards

Usage:
    service = RateLimitAnalyticsService(session)
    analytics = await service.get_rule_analytics(org_id, rule_id, start_time, end_time)
    summary = await service.get_org_summary(org_id, period="day")
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.orm import RateLimitHistory as RateLimitHistoryORM
from ..models.rate_limit_rules import (
    RateLimitAction,
    RateLimitAnalytics,
    RateLimitHit,
    RateLimitViolation,
)

logger = logging.getLogger(__name__)


class RateLimitAnalyticsService:
    """Aggregates rate limit history into actionable analytics.

    Provides methods to query and aggregate rate limit data for:
    - Organization-level summaries
    - Per-rule analytics
    - User-level usage patterns
    - Violation analysis and trends
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_rule_analytics(
        self,
        org_id: str,
        rule_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> RateLimitAnalytics:
        """Get analytics for a specific rate limit rule.

        Args:
            org_id: Organization ID
            rule_id: Rule ID to analyze
            start_time: Period start (defaults to 24h ago)
            end_time: Period end (defaults to now)

        Returns:
            RateLimitAnalytics with aggregated data
        """
        if end_time is None:
            end_time = datetime.now(UTC)
        if start_time is None:
            start_time = end_time - timedelta(hours=24)

        # Build base query
        base_filter = and_(
            RateLimitHistoryORM.org_id == org_id,
            RateLimitHistoryORM.rule_id == rule_id,
            RateLimitHistoryORM.timestamp >= start_time,
            RateLimitHistoryORM.timestamp <= end_time,
        )

        # Get aggregate stats
        stats_query = select(
            func.count().label("total_checks"),
            func.sum(case((RateLimitHistoryORM.allowed == True, 1), else_=0)).label("total_allowed"),  # noqa: E712
            func.sum(case((RateLimitHistoryORM.allowed == False, 1), else_=0)).label("total_blocked"),  # noqa: E712
            func.count(distinct(RateLimitHistoryORM.user_id)).label("unique_users"),
            func.max(RateLimitHistoryORM.current_count).label("peak_usage"),
        ).where(base_filter)

        stats_result = await self._session.execute(stats_query)
        stats = stats_result.one()

        # Get peak timestamp (when max usage occurred)
        peak_query = (
            select(RateLimitHistoryORM.timestamp)
            .where(
                and_(
                    base_filter,
                    RateLimitHistoryORM.current_count == stats.peak_usage,
                )
            )
            .limit(1)
        )
        peak_result = await self._session.execute(peak_query)
        peak_row = peak_result.scalar_one_or_none()

        # Calculate average usage percentage
        avg_query = select(
            func.avg(
                RateLimitHistoryORM.current_count * 100.0 / func.nullif(RateLimitHistoryORM.limit_value, 0)
            ).label("avg_percent")
        ).where(base_filter)
        avg_result = await self._session.execute(avg_query)
        avg_percent = avg_result.scalar() or 0.0

        return RateLimitAnalytics(
            rule_id=rule_id,
            org_id=org_id,
            period_start=start_time,
            period_end=end_time,
            total_checks=stats.total_checks or 0,
            total_allowed=stats.total_allowed or 0,
            total_blocked=stats.total_blocked or 0,
            unique_users=stats.unique_users or 0,
            peak_usage=stats.peak_usage or 0,
            peak_timestamp=peak_row,
            avg_usage_percent=round(float(avg_percent), 2),
        )

    async def get_org_summary(
        self,
        org_id: str,
        period: str = "day",  # "hour", "day", "week", "month"
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> RateLimitAnalytics:
        """Get organization-wide rate limit analytics summary.

        Args:
            org_id: Organization ID
            period: Time period preset ("hour", "day", "week", "month")
            start_time: Override period start
            end_time: Override period end

        Returns:
            RateLimitAnalytics with org-wide aggregated data
        """
        if end_time is None:
            end_time = datetime.now(UTC)

        if start_time is None:
            period_deltas = {
                "hour": timedelta(hours=1),
                "day": timedelta(days=1),
                "week": timedelta(weeks=1),
                "month": timedelta(days=30),
            }
            start_time = end_time - period_deltas.get(period, timedelta(days=1))

        base_filter = and_(
            RateLimitHistoryORM.org_id == org_id,
            RateLimitHistoryORM.timestamp >= start_time,
            RateLimitHistoryORM.timestamp <= end_time,
        )

        # Get aggregate stats across all rules
        stats_query = select(
            func.count().label("total_checks"),
            func.sum(case((RateLimitHistoryORM.allowed == True, 1), else_=0)).label("total_allowed"),  # noqa: E712
            func.sum(case((RateLimitHistoryORM.allowed == False, 1), else_=0)).label("total_blocked"),  # noqa: E712
            func.count(distinct(RateLimitHistoryORM.user_id)).label("unique_users"),
            func.max(RateLimitHistoryORM.current_count).label("peak_usage"),
        ).where(base_filter)

        stats_result = await self._session.execute(stats_query)
        stats = stats_result.one()

        # Get peak timestamp
        peak_query = (
            select(RateLimitHistoryORM.timestamp)
            .where(
                and_(
                    base_filter,
                    RateLimitHistoryORM.current_count == stats.peak_usage,
                )
            )
            .limit(1)
        )
        peak_result = await self._session.execute(peak_query)
        peak_row = peak_result.scalar_one_or_none()

        # Calculate average usage percentage
        avg_query = select(
            func.avg(
                RateLimitHistoryORM.current_count * 100.0 / func.nullif(RateLimitHistoryORM.limit_value, 0)
            ).label("avg_percent")
        ).where(base_filter)
        avg_result = await self._session.execute(avg_query)
        avg_percent = avg_result.scalar() or 0.0

        return RateLimitAnalytics(
            rule_id=None,  # Org-wide
            org_id=org_id,
            period_start=start_time,
            period_end=end_time,
            total_checks=stats.total_checks or 0,
            total_allowed=stats.total_allowed or 0,
            total_blocked=stats.total_blocked or 0,
            unique_users=stats.unique_users or 0,
            peak_usage=stats.peak_usage or 0,
            peak_timestamp=peak_row,
            avg_usage_percent=round(float(avg_percent), 2),
        )

    async def get_violations(
        self,
        org_id: str,
        rule_id: str | None = None,
        user_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RateLimitViolation]:
        """Get list of rate limit violations.

        Args:
            org_id: Organization ID
            rule_id: Optional rule ID filter
            user_id: Optional user ID filter
            start_time: Period start
            end_time: Period end
            limit: Max results
            offset: Pagination offset

        Returns:
            List of RateLimitViolation records
        """
        if end_time is None:
            end_time = datetime.now(UTC)
        if start_time is None:
            start_time = end_time - timedelta(hours=24)

        filters = [
            RateLimitHistoryORM.org_id == org_id,
            RateLimitHistoryORM.allowed == False,  # noqa: E712
            RateLimitHistoryORM.timestamp >= start_time,
            RateLimitHistoryORM.timestamp <= end_time,
        ]

        if rule_id:
            filters.append(RateLimitHistoryORM.rule_id == rule_id)
        if user_id:
            filters.append(RateLimitHistoryORM.user_id == user_id)

        query = (
            select(RateLimitHistoryORM)
            .where(and_(*filters))
            .order_by(RateLimitHistoryORM.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self._session.execute(query)
        rows = result.scalars().all()

        violations = []
        for row in rows:
            action = RateLimitAction.REJECT
            if row.action_taken == "throttled":
                action = RateLimitAction.THROTTLE
            elif row.action_taken == "logged":
                action = RateLimitAction.LOG_ONLY

            violations.append(
                RateLimitViolation(
                    rule_id=row.rule_id or "unknown",
                    org_id=row.org_id,
                    timestamp=row.timestamp,
                    user_id=row.user_id,
                    api_key_id=row.api_key_id,
                    endpoint=row.endpoint or "unknown",
                    current_count=row.current_count,
                    limit=row.limit_value,
                    action_taken=action,
                )
            )

        return violations

    async def get_violations_count(
        self,
        org_id: str,
        rule_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> int:
        """Get count of violations in a time period.

        Args:
            org_id: Organization ID
            rule_id: Optional rule ID filter
            start_time: Period start (defaults to 24h ago)
            end_time: Period end (defaults to now)

        Returns:
            Count of violations
        """
        if end_time is None:
            end_time = datetime.now(UTC)
        if start_time is None:
            start_time = end_time - timedelta(hours=24)

        filters = [
            RateLimitHistoryORM.org_id == org_id,
            RateLimitHistoryORM.allowed == False,  # noqa: E712
            RateLimitHistoryORM.timestamp >= start_time,
            RateLimitHistoryORM.timestamp <= end_time,
        ]

        if rule_id:
            filters.append(RateLimitHistoryORM.rule_id == rule_id)

        query = select(func.count()).where(and_(*filters))
        result = await self._session.execute(query)
        return result.scalar() or 0

    async def get_recent_hits(
        self,
        org_id: str,
        rule_id: str | None = None,
        limit: int = 50,
    ) -> list[RateLimitHit]:
        """Get recent rate limit hits (checks).

        Args:
            org_id: Organization ID
            rule_id: Optional rule ID filter
            limit: Max results

        Returns:
            List of recent RateLimitHit records
        """
        filters = [RateLimitHistoryORM.org_id == org_id]
        if rule_id:
            filters.append(RateLimitHistoryORM.rule_id == rule_id)

        query = (
            select(RateLimitHistoryORM)
            .where(and_(*filters))
            .order_by(RateLimitHistoryORM.timestamp.desc())
            .limit(limit)
        )

        result = await self._session.execute(query)
        rows = result.scalars().all()

        hits = []
        for row in rows:
            hits.append(
                RateLimitHit(
                    rule_id=row.rule_id or "unknown",
                    org_id=row.org_id,
                    timestamp=row.timestamp,
                    allowed=row.allowed,
                    user_id=row.user_id,
                    endpoint=row.endpoint,
                    current_count=row.current_count,
                    limit=row.limit_value,
                )
            )

        return hits

    async def get_top_users_by_usage(
        self,
        org_id: str,
        rule_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get top users by rate limit usage.

        Args:
            org_id: Organization ID
            rule_id: Optional rule ID filter
            start_time: Period start
            end_time: Period end
            limit: Max users to return

        Returns:
            List of dicts with user_id, total_requests, violations
        """
        if end_time is None:
            end_time = datetime.now(UTC)
        if start_time is None:
            start_time = end_time - timedelta(hours=24)

        filters = [
            RateLimitHistoryORM.org_id == org_id,
            RateLimitHistoryORM.user_id.isnot(None),
            RateLimitHistoryORM.timestamp >= start_time,
            RateLimitHistoryORM.timestamp <= end_time,
        ]

        if rule_id:
            filters.append(RateLimitHistoryORM.rule_id == rule_id)

        query = (
            select(
                RateLimitHistoryORM.user_id,
                func.count().label("total_requests"),
                func.sum(case((RateLimitHistoryORM.allowed == False, 1), else_=0)).label("violations"),  # noqa: E712
                func.max(RateLimitHistoryORM.current_count).label("peak_count"),
            )
            .where(and_(*filters))
            .group_by(RateLimitHistoryORM.user_id)
            .order_by(func.count().desc())
            .limit(limit)
        )

        result = await self._session.execute(query)
        rows = result.all()

        return [
            {
                "user_id": row.user_id,
                "total_requests": row.total_requests,
                "violations": row.violations or 0,
                "peak_count": row.peak_count or 0,
            }
            for row in rows
        ]

    async def get_top_endpoints_by_usage(
        self,
        org_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get top endpoints by rate limit usage.

        Args:
            org_id: Organization ID
            start_time: Period start
            end_time: Period end
            limit: Max endpoints to return

        Returns:
            List of dicts with endpoint, total_requests, violations
        """
        if end_time is None:
            end_time = datetime.now(UTC)
        if start_time is None:
            start_time = end_time - timedelta(hours=24)

        filters = [
            RateLimitHistoryORM.org_id == org_id,
            RateLimitHistoryORM.endpoint.isnot(None),
            RateLimitHistoryORM.timestamp >= start_time,
            RateLimitHistoryORM.timestamp <= end_time,
        ]

        query = (
            select(
                RateLimitHistoryORM.endpoint,
                func.count().label("total_requests"),
                func.sum(case((RateLimitHistoryORM.allowed == False, 1), else_=0)).label("violations"),  # noqa: E712
            )
            .where(and_(*filters))
            .group_by(RateLimitHistoryORM.endpoint)
            .order_by(func.count().desc())
            .limit(limit)
        )

        result = await self._session.execute(query)
        rows = result.all()

        return [
            {
                "endpoint": row.endpoint,
                "total_requests": row.total_requests,
                "violations": row.violations or 0,
            }
            for row in rows
        ]

    async def get_hourly_trend(
        self,
        org_id: str,
        rule_id: str | None = None,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Get hourly usage trend.

        Args:
            org_id: Organization ID
            rule_id: Optional rule ID filter
            hours: Number of hours to look back

        Returns:
            List of dicts with hour, total_requests, violations, avg_usage
        """
        end_time = datetime.now(UTC)
        start_time = end_time - timedelta(hours=hours)

        filters = [
            RateLimitHistoryORM.org_id == org_id,
            RateLimitHistoryORM.timestamp >= start_time,
            RateLimitHistoryORM.timestamp <= end_time,
        ]

        if rule_id:
            filters.append(RateLimitHistoryORM.rule_id == rule_id)

        # Extract hour and aggregate
        hour_expr = func.date_trunc("hour", RateLimitHistoryORM.timestamp)

        query = (
            select(
                hour_expr.label("hour"),
                func.count().label("total_requests"),
                func.sum(case((RateLimitHistoryORM.allowed == False, 1), else_=0)).label("violations"),  # noqa: E712
                func.avg(
                    RateLimitHistoryORM.current_count
                    * 100.0
                    / func.nullif(RateLimitHistoryORM.limit_value, 0)
                ).label("avg_usage_percent"),
            )
            .where(and_(*filters))
            .group_by(hour_expr)
            .order_by(hour_expr)
        )

        result = await self._session.execute(query)
        rows = result.all()

        return [
            {
                "hour": row.hour.isoformat() if row.hour else None,
                "total_requests": row.total_requests,
                "violations": row.violations or 0,
                "avg_usage_percent": round(float(row.avg_usage_percent or 0), 2),
            }
            for row in rows
        ]

    async def cleanup_old_history(
        self,
        org_id: str,
        retention_days: int = 30,
    ) -> int:
        """Delete old rate limit history records.

        Args:
            org_id: Organization ID
            retention_days: Keep records newer than this many days

        Returns:
            Number of deleted records
        """
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        # Use delete with returning to count
        from sqlalchemy import delete

        stmt = delete(RateLimitHistoryORM).where(
            and_(
                RateLimitHistoryORM.org_id == org_id,
                RateLimitHistoryORM.timestamp < cutoff,
            )
        )

        result = await self._session.execute(stmt)
        await self._session.commit()

        # rowcount is available on CursorResult from delete operations
        return getattr(result, "rowcount", 0) or 0


async def get_rate_limit_analytics_service(session: AsyncSession) -> RateLimitAnalyticsService:
    """FastAPI dependency for RateLimitAnalyticsService."""
    return RateLimitAnalyticsService(session)
