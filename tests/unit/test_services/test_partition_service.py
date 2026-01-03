"""Unit tests for PartitionService.

Tests for automatic partition management of audit_logs table.
"""

import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_server.services.partition_service import (
    DEFAULT_MONTHS_AHEAD,
    DEFAULT_RETENTION_DAYS,
    PARTITION_NAME_PATTERN,
    PartitionService,
    _add_months,
    partition_service,
)


class TestAddMonths:
    """Test the _add_months helper function."""

    def test_add_one_month(self):
        """Test adding one month."""
        dt = datetime(2026, 1, 15, tzinfo=UTC)
        result = _add_months(dt, 1)
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 15

    def test_add_month_year_rollover(self):
        """Test adding month with year rollover."""
        dt = datetime(2026, 12, 15, tzinfo=UTC)
        result = _add_months(dt, 1)
        assert result.year == 2027
        assert result.month == 1
        assert result.day == 15

    def test_add_multiple_months(self):
        """Test adding multiple months."""
        dt = datetime(2026, 1, 15, tzinfo=UTC)
        result = _add_months(dt, 5)
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 15

    def test_add_months_with_day_overflow(self):
        """Test adding month when day would overflow (Jan 31 + 1 month)."""
        dt = datetime(2026, 1, 31, tzinfo=UTC)
        result = _add_months(dt, 1)
        assert result.year == 2026
        assert result.month == 2
        assert result.day == 28  # Feb doesn't have 31 days

    def test_add_negative_months(self):
        """Test subtracting months."""
        dt = datetime(2026, 3, 15, tzinfo=UTC)
        result = _add_months(dt, -2)
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 15

    def test_subtract_month_year_rollback(self):
        """Test subtracting month with year rollback."""
        dt = datetime(2026, 1, 15, tzinfo=UTC)
        result = _add_months(dt, -1)
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 15


class TestPartitionNamePattern:
    """Test the partition name regex pattern."""

    def test_valid_partition_name(self):
        """Test valid partition name matches."""
        assert PARTITION_NAME_PATTERN.match("audit_logs_y2026m01")
        assert PARTITION_NAME_PATTERN.match("audit_logs_y2025m12")
        assert PARTITION_NAME_PATTERN.match("audit_logs_y2030m06")

    def test_invalid_partition_names(self):
        """Test invalid partition names don't match."""
        assert not PARTITION_NAME_PATTERN.match("audit_logs_y26m01")  # 2-digit year
        assert not PARTITION_NAME_PATTERN.match("audit_logs_y2026m1")  # 1-digit month
        assert not PARTITION_NAME_PATTERN.match("audit_logs_2026m01")  # Missing y
        assert not PARTITION_NAME_PATTERN.match("other_table_y2026m01")  # Wrong prefix


class TestPartitionServiceInit:
    """Test PartitionService initialization."""

    def test_singleton_exists(self):
        """Test that singleton instance exists."""
        assert partition_service is not None
        assert isinstance(partition_service, PartitionService)

    def test_create_new_instance(self):
        """Test creating new instance."""
        service = PartitionService()
        assert service is not None
        assert service.TABLE_NAME == "audit_logs"
        assert service.PARTITION_PREFIX == "audit_logs_y"


class TestPartitionServicePartitionName:
    """Test _partition_name method."""

    def test_january(self):
        """Test partition name for January."""
        service = PartitionService()
        dt = datetime(2026, 1, 15, tzinfo=UTC)
        assert service._partition_name(dt) == "audit_logs_y2026m01"

    def test_december(self):
        """Test partition name for December."""
        service = PartitionService()
        dt = datetime(2026, 12, 25, tzinfo=UTC)
        assert service._partition_name(dt) == "audit_logs_y2026m12"

    def test_month_padding(self):
        """Test that single-digit months are zero-padded."""
        service = PartitionService()
        dt = datetime(2026, 9, 1, tzinfo=UTC)
        assert service._partition_name(dt) == "audit_logs_y2026m09"


class TestPartitionServiceParsePartitionDate:
    """Test _parse_partition_date method."""

    def test_valid_partition_name(self):
        """Test parsing valid partition name."""
        service = PartitionService()
        result = service._parse_partition_date("audit_logs_y2026m01")
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 1
        assert result.tzinfo == UTC

    def test_invalid_partition_name(self):
        """Test parsing invalid partition name returns None."""
        service = PartitionService()
        assert service._parse_partition_date("invalid_name") is None
        assert service._parse_partition_date("audit_logs_y26m01") is None
        assert service._parse_partition_date("") is None

    def test_invalid_date_values(self):
        """Test parsing with invalid date values returns None."""
        service = PartitionService()
        # Month 13 is invalid
        assert service._parse_partition_date("audit_logs_y2026m13") is None
        # Month 00 is invalid
        assert service._parse_partition_date("audit_logs_y2026m00") is None


class TestPartitionServiceEnsureFuturePartitions:
    """Test ensure_future_partitions method."""

    @pytest.mark.asyncio
    async def test_creates_partitions(self):
        """Test that partitions are created."""
        service = PartitionService()

        # Mock the internal method
        created_partitions = []

        async def mock_create(dt):
            name = service._partition_name(dt)
            created_partitions.append(name)
            return True  # Newly created

        with patch.object(
            service, "_create_partition_if_not_exists", side_effect=mock_create
        ):
            result = await service.ensure_future_partitions(months_ahead=2)

        # Should create current + 2 future = 3 partitions
        assert len(result) == 3
        assert len(created_partitions) == 3

    @pytest.mark.asyncio
    async def test_skips_existing_partitions(self):
        """Test that existing partitions are skipped."""
        service = PartitionService()

        async def mock_create(dt):
            return False  # Already exists

        with patch.object(
            service, "_create_partition_if_not_exists", side_effect=mock_create
        ):
            result = await service.ensure_future_partitions()

        # No new partitions created
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_default_months_ahead(self):
        """Test default months_ahead value."""
        service = PartitionService()
        call_count = 0

        async def mock_create(dt):
            nonlocal call_count
            call_count += 1
            return True

        with patch.object(
            service, "_create_partition_if_not_exists", side_effect=mock_create
        ):
            await service.ensure_future_partitions()

        # Default is 3 months ahead + current = 4
        assert call_count == DEFAULT_MONTHS_AHEAD + 1


class TestPartitionServiceCleanupOldPartitions:
    """Test cleanup_old_partitions method."""

    @pytest.mark.asyncio
    async def test_drops_old_partitions(self):
        """Test that old partitions are dropped."""
        service = PartitionService()

        # Mock list to return old partitions
        old_partitions = ["audit_logs_y2025m01", "audit_logs_y2025m02"]

        async def mock_list():
            return old_partitions

        async def mock_drop(name):
            return True

        with (
            patch.object(service, "_list_partitions", side_effect=mock_list),
            patch.object(service, "_drop_partition", side_effect=mock_drop),
        ):
            result = await service.cleanup_old_partitions(retention_days=90)

        assert len(result) == 2
        assert "audit_logs_y2025m01" in result
        assert "audit_logs_y2025m02" in result

    @pytest.mark.asyncio
    async def test_keeps_recent_partitions(self):
        """Test that recent partitions are kept."""
        service = PartitionService()

        # Current date partitions should be kept
        now = datetime.now(UTC)
        current_partition = service._partition_name(now)

        async def mock_list():
            return [current_partition]

        async def mock_drop(name):
            return True

        with (
            patch.object(service, "_list_partitions", side_effect=mock_list),
            patch.object(service, "_drop_partition", side_effect=mock_drop) as drop_mock,
        ):
            result = await service.cleanup_old_partitions()

        # Current partition should not be dropped
        assert len(result) == 0
        drop_mock.assert_not_called()


class TestPartitionServiceCreatePartitionForDate:
    """Test create_partition_for_date method."""

    @pytest.mark.asyncio
    async def test_creates_new_partition(self):
        """Test creating a new partition for a date."""
        service = PartitionService()
        dt = datetime(2030, 6, 15, tzinfo=UTC)

        async def mock_create(target_dt):
            return True  # Newly created

        with patch.object(
            service, "_create_partition_if_not_exists", side_effect=mock_create
        ):
            result = await service.create_partition_for_date(dt)

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_if_exists(self):
        """Test returns False when partition already exists."""
        service = PartitionService()
        dt = datetime(2026, 1, 15, tzinfo=UTC)

        async def mock_create(target_dt):
            return False  # Already exists

        with patch.object(
            service, "_create_partition_if_not_exists", side_effect=mock_create
        ):
            result = await service.create_partition_for_date(dt)

        assert result is False

    @pytest.mark.asyncio
    async def test_propagates_exceptions(self):
        """Test that exceptions are propagated to caller."""
        service = PartitionService()
        dt = datetime(2030, 1, 1, tzinfo=UTC)

        async def mock_create(target_dt):
            raise Exception("Database connection failed")

        with patch.object(
            service, "_create_partition_if_not_exists", side_effect=mock_create
        ):
            with pytest.raises(Exception, match="Database connection failed"):
                await service.create_partition_for_date(dt)


class TestPartitionServiceGetPartitionStats:
    """Test get_partition_stats method."""

    @pytest.mark.asyncio
    async def test_returns_stats(self):
        """Test that partition stats are returned."""
        service = PartitionService()

        # Mock the list and db calls
        async def mock_list():
            return ["audit_logs_y2026m01"]

        mock_engine = MagicMock()
        mock_conn = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1000

        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock(return_value=mock_result)

        mock_engine.begin.return_value = mock_conn

        with (
            patch.object(service, "_list_partitions", side_effect=mock_list),
            patch("src.agent_server.services.partition_service.db_manager") as mock_db,
        ):
            mock_db.get_engine.return_value = mock_engine
            result = await service.get_partition_stats()

        assert "audit_logs_y2026m01" in result
        assert result["audit_logs_y2026m01"] == 1000
