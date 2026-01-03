"""Partition Service for audit_logs table management.

This module implements automatic partition management for the audit_logs table.
PostgreSQL RANGE partitioning by timestamp requires pre-created partitions.

Key Features:
- Automatic future partition creation (default: 3 months ahead)
- Optional old partition cleanup (default: 90 days retention)
- Safe partition existence checks before creation
- Designed to run on application startup

Usage:
    from src.agent_server.services.partition_service import partition_service

    # In lifespan startup
    await partition_service.ensure_future_partitions()

    # Optional: cleanup old partitions (run periodically)
    await partition_service.cleanup_old_partitions()
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from sqlalchemy import text

from ..core.database import db_manager
from ..core.rls import set_rls_bypass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MONTHS_AHEAD: int = 3
DEFAULT_RETENTION_DAYS: int = 90
PARTITION_NAME_PATTERN: re.Pattern[str] = re.compile(r"^audit_logs_y(\d{4})m(\d{2})$")


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _add_months(dt: datetime, months: int) -> datetime:
    """Add months to a datetime, handling year rollover.

    Args:
        dt: Source datetime
        months: Number of months to add (can be negative)

    Returns:
        datetime: Result with proper year/month handling
    """
    month = dt.month + months
    year = dt.year

    # Handle year rollover
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1

    # Handle day overflow (e.g., Jan 31 + 1 month -> Feb 28)
    import calendar

    max_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, max_day)

    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Service Class
# ---------------------------------------------------------------------------


class PartitionService:
    """Service for managing audit_logs table partitions.

    This service ensures that:
    1. Future partitions exist before data arrives (prevents insert failures)
    2. Old partitions can be cleaned up after retention period

    Thread Safety:
    - All operations use database-level checks and are safe for concurrent use
    - Partition creation is idempotent (IF NOT EXISTS)

    Attributes:
        TABLE_NAME: The parent partitioned table name
        PARTITION_PREFIX: Naming prefix for partition tables
    """

    TABLE_NAME: ClassVar[str] = "audit_logs"
    PARTITION_PREFIX: ClassVar[str] = "audit_logs_y"

    def __init__(self) -> None:
        """Initialize the partition service."""
        pass

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    async def ensure_future_partitions(
        self,
        months_ahead: int = DEFAULT_MONTHS_AHEAD,
    ) -> list[str]:
        """Create partitions for upcoming months if they don't exist.

        This method should be called during application startup to ensure
        partitions exist for incoming audit data.

        Args:
            months_ahead: Number of future months to create (default: 3)

        Returns:
            list[str]: Names of newly created partitions

        Note:
            This is idempotent - existing partitions are skipped.
        """
        created: list[str] = []
        now = datetime.now(UTC)

        # Create current month + future months
        for i in range(months_ahead + 1):
            target = _add_months(now, i)
            partition_name = self._partition_name(target)

            if await self._create_partition_if_not_exists(target):
                created.append(partition_name)
                logger.info("Created partition: %s", partition_name)
            else:
                logger.debug("Partition already exists: %s", partition_name)

        if created:
            logger.info("Created %d new audit log partitions", len(created))
        else:
            logger.debug("All required partitions already exist")

        return created

    async def cleanup_old_partitions(
        self,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> list[str]:
        """Drop partitions older than retention period.

        This method removes partitions containing data older than the
        specified retention period. Use with caution.

        Args:
            retention_days: Keep partitions with data newer than this (default: 90)

        Returns:
            list[str]: Names of dropped partitions

        Warning:
            This permanently deletes data. Ensure you have backups if needed.
        """
        dropped: list[str] = []
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        cutoff_month = cutoff.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Get all existing partitions
        partitions = await self._list_partitions()

        for partition_name in partitions:
            partition_date = self._parse_partition_date(partition_name)
            if partition_date is None:
                continue

            # Check if partition is older than retention cutoff
            partition_end = _add_months(partition_date, 1)
            if partition_end <= cutoff_month:
                if await self._drop_partition(partition_name):
                    dropped.append(partition_name)
                    logger.info("Dropped old partition: %s", partition_name)

        if dropped:
            logger.info(
                "Cleaned up %d old audit log partitions (retention: %d days)",
                len(dropped),
                retention_days,
            )

        return dropped

    async def create_partition_for_date(self, dt: datetime) -> bool:
        """Create a partition for the given date if it doesn't exist.

        This method is designed to be called when an INSERT fails due to
        missing partition. It's idempotent - calling it multiple times
        for the same month is safe.

        Args:
            dt: Date requiring a partition

        Returns:
            bool: True if partition was created, False if already existed

        Raises:
            Exception: If partition creation fails (caller should handle)
        """
        partition_name = self._partition_name(dt)
        created = await self._create_partition_if_not_exists(dt)

        if created:
            logger.info(
                "Dynamic partition created: %s (triggered by date %s)",
                partition_name,
                dt.isoformat(),
            )
        else:
            logger.debug("Partition already exists: %s", partition_name)

        return created

    async def get_partition_stats(self) -> dict[str, int]:
        """Get statistics about current partitions.

        Returns:
            dict: Partition names mapped to row counts
        """
        partitions = await self._list_partitions()
        stats: dict[str, int] = {}

        engine = db_manager.get_engine()

        for partition_name in partitions:
            try:
                async with engine.begin() as conn:
                    await set_rls_bypass(conn)
                    # Use reltuples for fast estimate (not exact count)
                    count_sql = text("""
                        SELECT reltuples::bigint AS estimate
                        FROM pg_class
                        WHERE relname = :name
                    """)
                    result = await conn.execute(count_sql, {"name": partition_name})
                    row = result.scalar()
                    stats[partition_name] = int(row) if row else 0
            except Exception as e:
                logger.warning("Failed to get stats for %s: %s", partition_name, e)
                stats[partition_name] = -1

        return stats

    # ---------------------------------------------------------------------------
    # Internal Methods
    # ---------------------------------------------------------------------------

    def _partition_name(self, dt: datetime) -> str:
        """Generate partition name for a given date.

        Args:
            dt: Date within the target month

        Returns:
            str: Partition table name (e.g., 'audit_logs_y2026m01')
        """
        return f"{self.PARTITION_PREFIX}{dt.year}m{dt.month:02d}"

    def _parse_partition_date(self, partition_name: str) -> datetime | None:
        """Parse year/month from a partition name.

        Args:
            partition_name: Name like 'audit_logs_y2026m01'

        Returns:
            datetime | None: First day of the partition month, or None if invalid
        """
        match = PARTITION_NAME_PATTERN.match(partition_name)
        if not match:
            return None

        try:
            year = int(match.group(1))
            month = int(match.group(2))
            return datetime(year, month, 1, tzinfo=UTC)
        except ValueError:
            return None

    async def _create_partition_if_not_exists(self, dt: datetime) -> bool:
        """Create a partition for the given month if it doesn't exist.

        Args:
            dt: Date within the target month

        Returns:
            bool: True if created, False if already existed
        """
        engine = db_manager.get_engine()
        partition_name = self._partition_name(dt)

        # Calculate month boundaries
        month_start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = _add_months(month_start, 1)

        try:
            async with engine.begin() as conn:
                await set_rls_bypass(conn)
                # Check if partition exists
                check_sql = text("""
                    SELECT 1 FROM pg_tables
                    WHERE tablename = :name AND schemaname = 'public'
                """)
                result = await conn.execute(check_sql, {"name": partition_name})

                if result.scalar():
                    return False  # Already exists

                # Validate partition name for SQL injection prevention
                if not PARTITION_NAME_PATTERN.match(partition_name):
                    raise ValueError(f"Invalid partition name: {partition_name}")

                # Create partition (using f-string since we validated the name)
                create_sql = text(f"""
                    CREATE TABLE IF NOT EXISTS {partition_name}
                    PARTITION OF {self.TABLE_NAME}
                    FOR VALUES FROM ('{month_start.strftime('%Y-%m-%d')}')
                    TO ('{month_end.strftime('%Y-%m-%d')}')
                """)
                await conn.execute(create_sql)
                return True

        except Exception as e:
            logger.error("Failed to create partition %s: %s", partition_name, e)
            raise

    async def _list_partitions(self) -> list[str]:
        """List all existing audit_logs partitions.

        Returns:
            list[str]: Partition table names sorted by date
        """
        engine = db_manager.get_engine()

        try:
            async with engine.begin() as conn:
                await set_rls_bypass(conn)
                list_sql = text("""
                    SELECT inhrelid::regclass::text AS partition_name
                    FROM pg_inherits
                    WHERE inhparent = 'audit_logs'::regclass
                    ORDER BY partition_name
                """)
                result = await conn.execute(list_sql)
                rows = result.fetchall()
                return [row.partition_name for row in rows]
        except Exception as e:
            logger.warning("Failed to list partitions: %s", e)
            return []

    async def _drop_partition(self, partition_name: str) -> bool:
        """Drop a partition table.

        Args:
            partition_name: Name of the partition to drop

        Returns:
            bool: True if dropped, False if failed
        """
        engine = db_manager.get_engine()

        # Validate partition name for SQL injection prevention
        if not PARTITION_NAME_PATTERN.match(partition_name):
            logger.error("Invalid partition name for drop: %s", partition_name)
            return False

        try:
            async with engine.begin() as conn:
                await set_rls_bypass(conn)
                drop_sql = text(f"DROP TABLE IF EXISTS {partition_name}")
                await conn.execute(drop_sql)
                return True
        except Exception as e:
            logger.error("Failed to drop partition %s: %s", partition_name, e)
            return False


# ---------------------------------------------------------------------------
# Singleton Instance
# ---------------------------------------------------------------------------

partition_service = PartitionService()
