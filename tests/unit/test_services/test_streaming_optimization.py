"""Unit tests for streaming optimization features."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agent_server.services.broker import RunBroker
from src.agent_server.services.streaming_service import StreamingService


@pytest.mark.asyncio
async def test_broker_drop_oldest_backpressure(monkeypatch):
    monkeypatch.setenv("BROKER_QUEUE_MAXSIZE", "2")
    monkeypatch.setenv("BROKER_BACKPRESSURE_POLICY", "drop_oldest")

    broker = RunBroker("run-123")

    await broker.put("event-1", ("values", {"idx": 1}))
    await broker.put("event-2", ("values", {"idx": 2}))
    await broker.put("event-3", ("values", {"idx": 3}))

    remaining = [broker.queue.get_nowait(), broker.queue.get_nowait()]
    remaining_ids = [item[0] for item in remaining]

    assert remaining_ids == ["event-2", "event-3"]


@pytest.mark.asyncio
async def test_storage_batch_flush_on_threshold(monkeypatch):
    monkeypatch.setenv("EVENT_STORE_BATCH_SIZE", "2")

    service = StreamingService()

    with patch("src.agent_server.services.streaming_service.event_store") as mock_store:
        mock_store.store_events = AsyncMock()

        await service.store_event_from_raw("run-abc", "run-abc_event_1", ("values", {"a": 1}))
        assert mock_store.store_events.call_count == 0

        await service.store_event_from_raw("run-abc", "run-abc_event_2", ("values", {"a": 2}))
        mock_store.store_events.assert_called_once()

        args, _ = mock_store.store_events.call_args
        assert args[0] == "run-abc"
        assert len(args[1]) == 2


@pytest.mark.asyncio
async def test_cleanup_run_flushes_pending_batch(monkeypatch):
    monkeypatch.setenv("EVENT_STORE_BATCH_SIZE", "10")

    service = StreamingService()

    with patch("src.agent_server.services.streaming_service.event_store") as mock_store:
        mock_store.store_events = AsyncMock()

        await service.store_event_from_raw("run-def", "run-def_event_1", ("values", {"a": 1}))
        assert mock_store.store_events.call_count == 0

        await service.cleanup_run("run-def")
        mock_store.store_events.assert_called_once()

        args, _ = mock_store.store_events.call_args
        assert args[0] == "run-def"
        assert len(args[1]) == 1
