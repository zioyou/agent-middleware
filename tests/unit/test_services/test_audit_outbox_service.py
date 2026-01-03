"""Unit tests for AuditOutboxService

TDD: These tests are written BEFORE the implementation.
They define the expected behavior of the AuditOutboxService.

Test Categories:
1. AuditMetrics - Simple counter class
2. AuditOutboxService - Insert, mover lifecycle, batch processing
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_server.services.audit_outbox_service import (
    BATCH_SIZE,
    INSERT_TIMEOUT_SECONDS,
    MOVE_INTERVAL_SECONDS,
    AuditMetrics,
    AuditOutboxService,
    audit_outbox_service,
)


class TestConstants:
    """Test that constants are properly defined"""

    def test_batch_size_is_reasonable(self):
        """Test that BATCH_SIZE is a reasonable value"""
        assert BATCH_SIZE > 0
        assert BATCH_SIZE <= 1000

    def test_insert_timeout_is_reasonable(self):
        """Test that INSERT_TIMEOUT_SECONDS is reasonable"""
        assert INSERT_TIMEOUT_SECONDS > 0
        assert INSERT_TIMEOUT_SECONDS <= 5

    def test_move_interval_is_reasonable(self):
        """Test that MOVE_INTERVAL_SECONDS is reasonable"""
        assert MOVE_INTERVAL_SECONDS > 0
        assert MOVE_INTERVAL_SECONDS <= 60


class TestAuditMetrics:
    """Tests for AuditMetrics class"""

    def test_initial_values_are_zero(self):
        """Test that metrics start at zero"""
        metrics = AuditMetrics()
        assert metrics.inserted == 0
        assert metrics.moved == 0
        assert metrics.dropped == 0
        assert metrics.mover_errors == 0

    def test_increment_inserted(self):
        """Test incrementing inserted counter"""
        metrics = AuditMetrics()
        metrics.inserted += 1
        assert metrics.inserted == 1

    def test_increment_moved(self):
        """Test incrementing moved counter"""
        metrics = AuditMetrics()
        metrics.moved += 10
        assert metrics.moved == 10

    def test_increment_dropped(self):
        """Test incrementing dropped counter"""
        metrics = AuditMetrics()
        metrics.dropped += 5
        assert metrics.dropped == 5

    def test_increment_mover_errors(self):
        """Test incrementing mover_errors counter"""
        metrics = AuditMetrics()
        metrics.mover_errors += 2
        assert metrics.mover_errors == 2

    def test_reset(self):
        """Test that reset clears all counters"""
        metrics = AuditMetrics()
        metrics.inserted = 100
        metrics.moved = 90
        metrics.dropped = 5
        metrics.mover_errors = 3

        metrics.reset()

        assert metrics.inserted == 0
        assert metrics.moved == 0
        assert metrics.dropped == 0
        assert metrics.mover_errors == 0

    def test_to_dict(self):
        """Test dictionary conversion"""
        metrics = AuditMetrics()
        metrics.inserted = 100
        metrics.moved = 90
        metrics.dropped = 5
        metrics.mover_errors = 3

        result = metrics.to_dict()

        assert result["audit.inserted"] == 100
        assert result["audit.moved"] == 90
        assert result["audit.dropped"] == 5
        assert result["audit.mover_errors"] == 3


class TestAuditOutboxServiceInit:
    """Tests for AuditOutboxService initialization"""

    def test_service_initialization(self):
        """Test service initialization"""
        service = AuditOutboxService()

        assert service._mover_task is None
        assert service._running is False
        assert isinstance(service.metrics, AuditMetrics)

    def test_singleton_exists(self):
        """Test that singleton instance exists"""
        assert audit_outbox_service is not None
        assert isinstance(audit_outbox_service, AuditOutboxService)


class TestAuditOutboxServiceInsert:
    """Tests for AuditOutboxService.insert method"""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance for testing"""
        return AuditOutboxService()

    @pytest.mark.asyncio
    async def test_insert_success(self, service):
        """Test successful audit entry insertion"""
        payload = {
            "user_id": "test-user",
            "action": "CREATE",
            "resource_type": "assistant",
            "timestamp": datetime.now(UTC).isoformat(),
        }

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.return_value = mock_engine

            result = await service.insert(payload)

            assert result is not None  # Returns the generated ID
            assert service.metrics.inserted == 1
            assert service.metrics.dropped == 0

    @pytest.mark.asyncio
    async def test_insert_returns_id(self, service):
        """Test that insert returns a valid UUID"""
        payload = {"user_id": "test-user"}

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.return_value = mock_engine

            result = await service.insert(payload)

            # Should be a valid UUID string
            assert result is not None
            assert len(result) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_insert_timeout_drops_entry(self, service):
        """Test that insert timeout is handled gracefully"""
        payload = {"user_id": "test-user"}

        async def slow_operation(*args, **kwargs):
            await asyncio.sleep(INSERT_TIMEOUT_SECONDS + 1)

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = slow_operation

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.return_value = mock_engine

            result = await service.insert(payload)

            assert result is None
            assert service.metrics.dropped == 1
            assert service.metrics.inserted == 0

    @pytest.mark.asyncio
    async def test_insert_exception_drops_entry(self, service):
        """Test that exceptions during insert are handled"""
        payload = {"user_id": "test-user"}

        mock_engine = MagicMock()
        mock_engine.begin.side_effect = Exception("DB connection failed")

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.return_value = mock_engine

            result = await service.insert(payload)

            assert result is None
            assert service.metrics.dropped == 1

    @pytest.mark.asyncio
    async def test_insert_never_raises(self, service):
        """Test that insert never raises exceptions"""
        payload = {"user_id": "test-user"}

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.side_effect = Exception("Catastrophic failure")

            # Should not raise
            result = await service.insert(payload)

            assert result is None
            assert service.metrics.dropped == 1


class TestAuditOutboxServiceMoverLifecycle:
    """Tests for mover lifecycle (start/stop)"""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance"""
        return AuditOutboxService()

    @pytest.mark.asyncio
    async def test_start_mover_creates_task(self, service):
        """Test that start_mover creates a background task"""
        # Mock the move loop to prevent actual execution
        with patch.object(service, "_mover_loop", new_callable=AsyncMock):
            await service.start_mover()

            assert service._mover_task is not None
            assert service._running is True

            # Cleanup
            await service.stop_mover()

    @pytest.mark.asyncio
    async def test_start_mover_idempotent(self, service):
        """Test that calling start_mover multiple times is safe"""
        with patch.object(service, "_mover_loop", new_callable=AsyncMock):
            await service.start_mover()
            task1 = service._mover_task

            await service.start_mover()
            task2 = service._mover_task

            # Should be the same task
            assert task1 is task2

            # Cleanup
            await service.stop_mover()

    @pytest.mark.asyncio
    async def test_stop_mover_stops_task(self, service):
        """Test that stop_mover stops the background task"""
        with patch.object(service, "_mover_loop", new_callable=AsyncMock):
            with patch.object(service, "_move_batch", new_callable=AsyncMock):
                await service.start_mover()
                assert service._running is True

                await service.stop_mover()

                assert service._running is False

    @pytest.mark.asyncio
    async def test_stop_mover_flushes_remaining(self, service):
        """Test that stop_mover flushes remaining records"""
        flush_called = False

        async def mock_move_batch():
            nonlocal flush_called
            flush_called = True
            return 0

        with patch.object(service, "_mover_loop", new_callable=AsyncMock):
            with patch.object(service, "_move_batch", side_effect=mock_move_batch):
                await service.start_mover()
                await service.stop_mover()

                assert flush_called

    @pytest.mark.asyncio
    async def test_stop_mover_without_start(self, service):
        """Test that stop_mover is safe without start"""
        # Should not raise
        await service.stop_mover()

        assert service._running is False


class TestAuditOutboxServiceGetMetrics:
    """Tests for get_metrics method"""

    def test_get_metrics_returns_dict(self):
        """Test that get_metrics returns a dictionary"""
        service = AuditOutboxService()
        service.metrics.inserted = 100
        service.metrics.moved = 90

        result = service.get_metrics()

        assert isinstance(result, dict)
        assert result["audit.inserted"] == 100
        assert result["audit.moved"] == 90


class TestAuditOutboxServiceMoveBatch:
    """Tests for _move_batch method"""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance"""
        return AuditOutboxService()

    @pytest.mark.asyncio
    async def test_move_batch_empty(self, service):
        """Test move_batch with no records"""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []

        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_result

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.return_value = mock_engine

            moved = await service._move_batch()

            assert moved == 0
            assert service.metrics.moved == 0

    @pytest.mark.asyncio
    async def test_move_batch_processes_records(self, service):
        """Test move_batch processes records correctly"""
        # Create mock outbox records
        mock_row = MagicMock()
        mock_row.id = "outbox-1"
        mock_row.payload = {
            "id": "audit-1",
            "timestamp": datetime.now(UTC).isoformat(),
            "user_id": "user-1",
            "action": "CREATE",
            "resource_type": "assistant",
            "http_method": "POST",
            "path": "/assistants",
            "status_code": 200,
            "duration_ms": 100,
        }
        mock_row.created_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]

        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_result

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.return_value = mock_engine

            moved = await service._move_batch()

            assert moved == 1
            assert service.metrics.moved == 1

    @pytest.mark.asyncio
    async def test_move_batch_handles_error(self, service):
        """Test move_batch handles errors gracefully"""
        mock_engine = MagicMock()
        mock_engine.begin.side_effect = Exception("DB error")

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.return_value = mock_engine

            # Should not raise
            moved = await service._move_batch()

            assert moved == 0
            assert service.metrics.mover_errors == 1


class TestPartitionErrorDetection:
    """Tests for partition error detection and auto-creation."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return AuditOutboxService()

    def test_is_partition_error_no_partition_found(self, service):
        """Test detection of 'no partition found' error."""
        error = Exception('no partition of relation "audit_logs" found for row')
        assert service._is_partition_error(error) is True

    def test_is_partition_error_partition_constraint(self, service):
        """Test detection of 'partition constraint' error."""
        error = Exception("new row violates partition constraint")
        assert service._is_partition_error(error) is True

    def test_is_partition_error_partition_of_relation(self, service):
        """Test detection of 'partition of relation' error."""
        error = Exception('no partition of relation for value "2030-01-01"')
        assert service._is_partition_error(error) is True

    def test_is_partition_error_case_insensitive(self, service):
        """Test that partition error detection is case-insensitive."""
        error = Exception('NO PARTITION of relation "audit_logs" found')
        assert service._is_partition_error(error) is True

    def test_is_partition_error_regular_error(self, service):
        """Test that regular errors are not detected as partition errors."""
        error = Exception("Connection refused")
        assert service._is_partition_error(error) is False

    def test_is_partition_error_unique_violation(self, service):
        """Test that unique violation is not a partition error."""
        error = Exception("duplicate key value violates unique constraint")
        assert service._is_partition_error(error) is False


class TestPartitionAutoCreation:
    """Tests for automatic partition creation during batch move."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return AuditOutboxService()

    @pytest.mark.asyncio
    async def test_move_batch_creates_partition_on_error(self, service):
        """Test that partition is created when insert fails due to missing partition."""
        from datetime import UTC, datetime

        # Create mock outbox record
        mock_row = MagicMock()
        mock_row.id = "outbox-1"
        mock_row.payload = {
            "id": "audit-1",
            "timestamp": datetime.now(UTC).isoformat(),
            "user_id": "user-1",
            "action": "CREATE",
            "resource_type": "assistant",
            "http_method": "POST",
            "path": "/assistants",
            "status_code": 200,
            "duration_ms": 100,
        }
        mock_row.created_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]

        # Track operations
        insert_attempts = []
        partition_created = False

        # First savepoint fails with partition error, retry succeeds
        first_savepoint = True

        async def mock_begin_nested():
            nonlocal first_savepoint
            savepoint = AsyncMock()

            async def mock_commit():
                pass

            async def mock_rollback():
                pass

            savepoint.commit = mock_commit
            savepoint.rollback = mock_rollback
            return savepoint

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=mock_result)
        mock_conn.begin_nested = mock_begin_nested

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        # Make first execute fail with partition error, second succeed
        execute_call_count = [0]

        async def mock_execute(stmt, *args, **kwargs):
            execute_call_count[0] += 1
            # First call is SELECT, second is INSERT (fails), third is retry INSERT (succeeds)
            if execute_call_count[0] == 1:  # SELECT
                return mock_result
            elif execute_call_count[0] == 2:  # First INSERT - partition error
                raise Exception('no partition of relation "audit_logs" found for row')
            else:  # Retry and subsequent calls succeed
                return MagicMock()

        mock_conn.execute = mock_execute

        with (
            patch(
                "src.agent_server.services.audit_outbox_service.db_manager"
            ) as mock_db,
            patch(
                "src.agent_server.services.audit_outbox_service.partition_service"
            ) as mock_partition,
            patch(
                "src.agent_server.services.audit_outbox_service.set_rls_bypass"
            ) as mock_rls_bypass,
        ):
            mock_db.get_engine.return_value = mock_engine
            mock_partition.create_partition_for_date = AsyncMock(return_value=True)
            mock_rls_bypass.return_value = None

            moved = await service._move_batch()

            # Partition creation should have been called
            mock_partition.create_partition_for_date.assert_called_once()
            # Record should have been successfully moved after retry
            assert moved == 1
            assert service.metrics.moved == 1

    @pytest.mark.asyncio
    async def test_move_batch_falls_back_on_partition_creation_failure(self, service):
        """Test fallback to retry logic when partition creation fails."""
        from datetime import UTC, datetime

        mock_row = MagicMock()
        mock_row.id = "outbox-1"
        mock_row.payload = {
            "id": "audit-1",
            "timestamp": datetime.now(UTC).isoformat(),
            "user_id": "user-1",
            "action": "CREATE",
            "resource_type": "assistant",
        }
        mock_row.created_at = datetime.now(UTC)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]

        mock_conn = AsyncMock()

        call_count = [0]

        async def mock_execute(stmt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # SELECT
                return mock_result
            else:  # INSERT fails
                raise Exception('no partition of relation "audit_logs" found')

        mock_conn.execute = mock_execute
        mock_conn.begin_nested = AsyncMock(return_value=AsyncMock())

        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        with (
            patch(
                "src.agent_server.services.audit_outbox_service.db_manager"
            ) as mock_db,
            patch(
                "src.agent_server.services.audit_outbox_service.partition_service"
            ) as mock_partition,
            patch(
                "src.agent_server.services.audit_outbox_service.set_rls_bypass"
            ) as mock_rls_bypass,
        ):
            mock_db.get_engine.return_value = mock_engine
            mock_rls_bypass.return_value = None
            # Partition creation fails
            mock_partition.create_partition_for_date = AsyncMock(
                side_effect=Exception("Cannot create partition")
            )

            moved = await service._move_batch()

            # Partition creation was attempted
            mock_partition.create_partition_for_date.assert_called_once()
            # Record was not moved (will be retried)
            assert moved == 0
            # Retry count should be incremented
        assert service._retry_cache.get("outbox-1") == 1


class TestMoverDrainBehavior:
    """Tests for "drain until empty" mover loop behavior."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return AuditOutboxService()

    @pytest.mark.asyncio
    async def test_mover_drains_all_batches_before_sleep(self, service):
        """Test that mover processes all available batches before sleeping."""
        batch_counts = [5, 3, 0]
        call_index = [0]
        sleep_called = [False]

        async def mock_move_batch():
            idx = call_index[0]
            call_index[0] += 1
            if idx < len(batch_counts):
                return batch_counts[idx]
            return 0

        async def mock_sleep(duration):
            sleep_called[0] = True
            service._running = False

        with patch.object(service, "_move_batch", side_effect=mock_move_batch):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                service._running = True
                await service._mover_loop()

        assert call_index[0] == 3
        assert sleep_called[0] is True

    @pytest.mark.asyncio
    async def test_mover_sleeps_when_no_records(self, service):
        """Test that mover sleeps immediately when no records available."""
        sleep_called = [False]
        move_batch_calls = [0]

        async def mock_move_batch():
            move_batch_calls[0] += 1
            return 0

        async def mock_sleep(duration):
            sleep_called[0] = True
            service._running = False

        with patch.object(service, "_move_batch", side_effect=mock_move_batch):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                service._running = True
                await service._mover_loop()

        assert move_batch_calls[0] == 1
        assert sleep_called[0] is True

    @pytest.mark.asyncio
    async def test_mover_respects_shutdown_during_drain(self, service):
        """Test that mover stops draining when _running is set to False."""
        call_count = [0]

        async def mock_move_batch():
            call_count[0] += 1
            if call_count[0] == 2:
                service._running = False
            return 10

        with patch.object(service, "_move_batch", side_effect=mock_move_batch):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                service._running = True
                await service._mover_loop()

        assert call_count[0] == 2


class TestAuditOutboxServiceIntegration:
    """Integration-style tests for the service"""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Test full service lifecycle"""
        service = AuditOutboxService()

        # Initially not running
        assert service._running is False
        assert service._mover_task is None

        # Start mover
        with patch.object(service, "_mover_loop", new_callable=AsyncMock):
            with patch.object(service, "_move_batch", new_callable=AsyncMock):
                await service.start_mover()
                assert service._running is True

                # Stop mover
                await service.stop_mover()
                assert service._running is False

    @pytest.mark.asyncio
    async def test_metrics_accumulate(self):
        """Test that metrics accumulate correctly"""
        service = AuditOutboxService()

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "src.agent_server.services.audit_outbox_service.db_manager"
        ) as mock_db:
            mock_db.get_engine.return_value = mock_engine

            # Multiple successful inserts
            await service.insert({"data": "1"})
            await service.insert({"data": "2"})
            await service.insert({"data": "3"})

            assert service.metrics.inserted == 3

        # Reset and verify
        service.metrics.reset()
        assert service.metrics.inserted == 0
