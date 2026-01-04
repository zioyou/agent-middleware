"""StreamingService unit tests

테스트 커버리지 개선을 위한 핵심 함수 테스트
Target: ~60% coverage for streaming_service.py
"""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent_server.services.streaming_service import StreamingService


# =============================================================================
# Helper: Async generator factory
# =============================================================================
async def async_gen(*items):
    """Helper to create async generator from items."""
    for item in items:
        yield item


def make_fake_run(run_id: str = "run-123", status: str = "running") -> MagicMock:
    """Create a fake Run object for testing."""
    run = MagicMock()
    run.run_id = run_id
    run.status = status
    return run


def make_fake_broker(
    is_finished: bool = False,
    events: list[tuple[str, Any]] | None = None,
) -> MagicMock:
    """Create a fake RunBroker for testing."""
    broker = MagicMock()
    broker.is_finished.return_value = is_finished
    broker.put = AsyncMock()

    async def fake_aiter():
        for ev in events or []:
            yield ev

    broker.aiter = fake_aiter
    return broker


def make_fake_stored_event(
    event_id: str = "run-123_event_1",
    event: str = "values",
    data: dict | None = None,
) -> SimpleNamespace:
    """Create a fake stored event for testing."""
    return SimpleNamespace(id=event_id, event=event, data=data or {})


# =============================================================================
# TestStreamingServiceInit - 기존 테스트
# =============================================================================
class TestStreamingServiceInit:
    """StreamingService 초기화 테스트"""

    def test_initialization(self):
        """서비스가 올바르게 초기화되는지 검증"""
        service = StreamingService()

        assert service.event_counters == {}
        assert service.event_converter is not None
        assert service._storage_batches == {}
        assert service._storage_batch_size >= 1


# =============================================================================
# TestProcessInterruptUpdates - 기존 테스트
# =============================================================================
class TestProcessInterruptUpdates:
    """_process_interrupt_updates 메서드 테스트"""

    def setup_method(self):
        """각 테스트 전 StreamingService 인스턴스 생성"""
        self.service = StreamingService()

    def test_process_interrupt_updates_skip_non_interrupt(self):
        """인터럽트가 아닌 updates 이벤트는 스킵"""
        raw_event = ("updates", {"key": "value"})
        only_interrupt_updates = True

        processed_event, should_skip = self.service._process_interrupt_updates(
            raw_event, only_interrupt_updates
        )

        # 인터럽트가 아니므로 스킵
        assert should_skip is True

    def test_process_interrupt_updates_pass_interrupt(self):
        """인터럽트 업데이트는 values로 변환하여 통과"""
        raw_event = ("updates", {"__interrupt__": [{"type": "human"}]})
        only_interrupt_updates = True

        processed_event, should_skip = self.service._process_interrupt_updates(
            raw_event, only_interrupt_updates
        )

        # 인터럽트이므로 통과하고 values로 변환
        assert should_skip is False
        assert processed_event[0] == "values"

    def test_process_interrupt_updates_with_disabled_filter(self):
        """only_interrupt_updates=False일 때는 필터링 안함"""
        raw_event = ("updates", {"key": "value"})
        only_interrupt_updates = False

        processed_event, should_skip = self.service._process_interrupt_updates(
            raw_event, only_interrupt_updates
        )

        # 필터링 비활성화이므로 스킵 안함
        assert should_skip is False
        assert processed_event == raw_event

    def test_process_interrupt_updates_non_tuple_event(self):
        """튜플이 아닌 이벤트는 그대로 통과"""
        raw_event = {"event": "data"}
        only_interrupt_updates = True

        processed_event, should_skip = self.service._process_interrupt_updates(
            raw_event, only_interrupt_updates
        )

        assert should_skip is False
        assert processed_event == raw_event

    def test_process_interrupt_updates_empty_interrupt_list_skips(self):
        """__interrupt__가 빈 리스트면 스킵"""
        raw_event = ("updates", {"__interrupt__": []})
        only_interrupt_updates = True

        processed_event, should_skip = self.service._process_interrupt_updates(
            raw_event, only_interrupt_updates
        )

        assert should_skip is True


# =============================================================================
# TestStreamRunExecution - #1-4
# =============================================================================
class TestStreamRunExecution:
    """stream_run_execution 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_stream_run_execution_first_connection_yields_metadata_then_replay_then_live(
        self,
    ):
        """#1: 첫 연결 시 metadata → replay → live 순서로 이벤트 yield"""
        run = make_fake_run("run-123", "running")

        with (
            patch(
                "src.agent_server.services.streaming_service.create_metadata_event",
                return_value="META_EVENT",
            ),
            patch(
                "src.agent_server.services.streaming_service.generate_event_id",
                return_value="run-123_event_0",
            ),
            patch.object(
                self.service,
                "_replay_stored_events",
                return_value=async_gen("REPLAY1", "REPLAY2"),
            ),
            patch.object(
                self.service,
                "_stream_live_events",
                return_value=async_gen("LIVE1"),
            ),
        ):
            events = []
            async for ev in self.service.stream_run_execution(run, last_event_id=None):
                events.append(ev)

            assert events[0] == "META_EVENT"
            assert events[1] == "REPLAY1"
            assert events[2] == "REPLAY2"
            assert events[3] == "LIVE1"
            assert len(events) == 4

    @pytest.mark.asyncio
    async def test_stream_run_execution_reconnect_skips_metadata(self):
        """#2: 재연결 시 last_event_id 제공하면 metadata 스킵"""
        run = make_fake_run("run-123", "running")

        with (
            patch("src.agent_server.services.streaming_service.create_metadata_event") as mock_meta,
            patch.object(
                self.service,
                "_replay_stored_events",
                return_value=async_gen("REPLAY1"),
            ),
            patch.object(
                self.service,
                "_stream_live_events",
                return_value=async_gen("LIVE1"),
            ),
            patch.object(self.service, "_extract_event_sequence", return_value=42),
        ):
            events = []
            async for ev in self.service.stream_run_execution(run, last_event_id="run-123_event_42"):
                events.append(ev)

            # metadata 생성 안됨
            mock_meta.assert_not_called()
            # replay와 live만 yield
            assert "REPLAY1" in events
            assert "LIVE1" in events
            assert "META_EVENT" not in events

    @pytest.mark.asyncio
    async def test_stream_run_execution_cancelled_calls_cancel_background_task(self):
        """#3: CancelledError 발생 + cancel_on_disconnect=True → _cancel_background_task 호출"""
        run = make_fake_run("run-123", "running")

        async def raise_cancelled(*args, **kwargs):
            raise asyncio.CancelledError()
            yield  # pragma: no cover - never reached

        with (
            patch(
                "src.agent_server.services.streaming_service.create_metadata_event",
                return_value="META",
            ),
            patch(
                "src.agent_server.services.streaming_service.generate_event_id",
                return_value="run-123_event_0",
            ),
            patch.object(self.service, "_replay_stored_events", return_value=async_gen()),
            patch.object(self.service, "_stream_live_events", side_effect=raise_cancelled),
            patch.object(self.service, "_cancel_background_task") as mock_cancel,
        ):
            with pytest.raises(asyncio.CancelledError):
                events = []
                async for ev in self.service.stream_run_execution(
                    run, last_event_id=None, cancel_on_disconnect=True
                ):
                    events.append(ev)

            mock_cancel.assert_called_once_with("run-123")

    @pytest.mark.asyncio
    async def test_stream_run_execution_exception_yields_error_event(self):
        """#4: 예외 발생 시 에러 이벤트 yield"""
        run = make_fake_run("run-123", "running")

        async def raise_error(*args, **kwargs):
            raise ValueError("boom")
            yield  # pragma: no cover

        with (
            patch(
                "src.agent_server.services.streaming_service.create_metadata_event",
                return_value="META",
            ),
            patch(
                "src.agent_server.services.streaming_service.generate_event_id",
                return_value="run-123_event_0",
            ),
            patch.object(self.service, "_replay_stored_events", side_effect=raise_error),
            patch(
                "src.agent_server.services.streaming_service.create_error_event",
                return_value="ERROR_EVENT",
            ) as mock_err,
        ):
            events = []
            async for ev in self.service.stream_run_execution(run, last_event_id=None):
                events.append(ev)

            # 에러 이벤트 포함
            assert "ERROR_EVENT" in events
            mock_err.assert_called_once_with("boom")


# =============================================================================
# TestReplayStoredEvents - #5-7
# =============================================================================
class TestReplayStoredEvents:
    """_replay_stored_events 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_replay_stored_events_uses_events_since_when_last_event_id_provided(
        self,
    ):
        """#5: last_event_id 있으면 stream_events_since 사용"""
        stored1 = make_fake_stored_event("run-123_event_43")
        stored2 = make_fake_stored_event("run-123_event_44")

        with (
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
            patch.object(self.service, "_stored_event_to_sse", side_effect=["SSE1", "SSE2"]),
        ):
            mock_store.stream_events_since = MagicMock(return_value=async_gen(stored1, stored2))

            events = []
            async for ev in self.service._replay_stored_events("run-123", "run-123_event_42"):
                events.append(ev)

            mock_store.stream_events_since.assert_called_once_with("run-123", "run-123_event_42")
            assert events == ["SSE1", "SSE2"]

    @pytest.mark.asyncio
    async def test_replay_stored_events_uses_all_events_when_no_last_event_id(self):
        """#6: last_event_id 없으면 stream_all_events 사용"""
        stored1 = make_fake_stored_event("run-123_event_1")

        with (
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
            patch.object(self.service, "_stored_event_to_sse", return_value="SSE1"),
        ):
            mock_store.stream_all_events = MagicMock(return_value=async_gen(stored1))

            events = []
            async for ev in self.service._replay_stored_events("run-123", None):
                events.append(ev)

            mock_store.stream_all_events.assert_called_once_with("run-123")
            assert events == ["SSE1"]

    @pytest.mark.asyncio
    async def test_replay_stored_events_skips_none_conversions(self):
        """#7: _stored_event_to_sse가 None 반환하면 스킵"""
        stored1 = make_fake_stored_event("run-123_event_1")
        stored2 = make_fake_stored_event("run-123_event_2")

        with (
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
            patch.object(self.service, "_stored_event_to_sse", side_effect=[None, "SSE2"]),
        ):
            mock_store.stream_all_events = MagicMock(return_value=async_gen(stored1, stored2))

            events = []
            async for ev in self.service._replay_stored_events("run-123", None):
                events.append(ev)

            # None인 첫 번째는 스킵, 두 번째만 포함
            assert events == ["SSE2"]


# =============================================================================
# TestStreamLiveEvents - #8-10
# =============================================================================
class TestStreamLiveEvents:
    """_stream_live_events 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_stream_live_events_terminal_run_and_finished_broker_yields_nothing(
        self,
    ):
        """#8: run.status가 terminal이고 broker.is_finished()=True면 즉시 종료"""
        run = make_fake_run("run-123", "completed")
        broker = make_fake_broker(is_finished=True, events=[("ev1", "payload")])

        with patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm:
            mock_bm.get_or_create_broker.return_value = broker

            events = []
            async for ev in self.service._stream_live_events(run, 0):
                events.append(ev)

            assert events == []

    @pytest.mark.asyncio
    async def test_stream_live_events_skips_duplicates_using_last_sent_sequence(self):
        """#9: last_sent_sequence보다 작거나 같은 시퀀스는 스킵"""
        run = make_fake_run("run-123", "running")
        # events: seq 1, 2, 3
        broker = make_fake_broker(
            is_finished=False,
            events=[
                ("run-123_event_1", ("values", {"a": 1})),
                ("run-123_event_2", ("values", {"a": 2})),
                ("run-123_event_3", ("values", {"a": 3})),
            ],
        )

        with (
            patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm,
            patch.object(self.service, "_convert_raw_to_sse", side_effect=["SSE3"]) as mock_conv,
        ):
            mock_bm.get_or_create_broker.return_value = broker

            # last_sent_sequence=2이므로 seq 1, 2 스킵하고 seq 3만 변환
            events = []
            async for ev in self.service._stream_live_events(run, last_sent_sequence=2):
                events.append(ev)

            assert events == ["SSE3"]
            # _convert_raw_to_sse는 seq 3에 대해서만 호출
            mock_conv.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_live_events_does_not_yield_when_conversion_returns_none(self):
        """#10: _convert_raw_to_sse가 None 반환하면 yield 안함"""
        run = make_fake_run("run-123", "running")
        broker = make_fake_broker(
            is_finished=False,
            events=[("run-123_event_1", ("values", {"a": 1}))],
        )

        with (
            patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm,
            patch.object(self.service, "_convert_raw_to_sse", return_value=None),
        ):
            mock_bm.get_or_create_broker.return_value = broker

            events = []
            async for ev in self.service._stream_live_events(run, last_sent_sequence=0):
                events.append(ev)

            assert events == []


# =============================================================================
# TestPutToBroker - #11-12
# =============================================================================
class TestPutToBroker:
    """put_to_broker 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_put_to_broker_enqueues_processed_event(self):
        """#11: 정상 이벤트는 broker.put()으로 큐에 추가"""
        broker = make_fake_broker()

        with (
            patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm,
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(("values", {"processed": True}), False),
            ),
        ):
            mock_bm.get_or_create_broker.return_value = broker

            await self.service.put_to_broker("run-123", "run-123_event_1", ("values", {"original": True}))

            broker.put.assert_awaited_once_with("run-123_event_1", ("values", {"processed": True}))

    @pytest.mark.asyncio
    async def test_put_to_broker_skips_when_interrupt_filter_says_skip(self):
        """#12: should_skip=True면 broker.put() 호출 안함"""
        broker = make_fake_broker()

        with (
            patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm,
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(("updates", {}), True),  # should_skip=True
            ),
        ):
            mock_bm.get_or_create_broker.return_value = broker

            await self.service.put_to_broker(
                "run-123",
                "run-123_event_1",
                ("updates", {}),
                only_interrupt_updates=True,
            )

            broker.put.assert_not_awaited()


# =============================================================================
# TestStoreEventFromRaw - #13-16, #22-23
# =============================================================================
class TestStoreEventFromRaw:
    """store_event_from_raw 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()
        self.service._storage_batch_size = 1  # flush 즉시 발생하도록

    @pytest.mark.asyncio
    async def test_store_event_from_raw_messages_builds_event_and_flushes(self):
        """#13: messages 이벤트 처리 및 flush"""
        chunk = {"content": "Hello"}
        meta = {"sender": "ai"}

        with (
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(("messages", (chunk, meta)), False),
            ),
            patch(
                "src.agent_server.services.streaming_service.build_sse_event",
                return_value="SSE_MSG",
            ) as mock_build,
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
        ):
            mock_store.store_events = AsyncMock()

            await self.service.store_event_from_raw("run-123", "run-123_event_1", ("messages", (chunk, meta)))

            # build_sse_event 호출 확인
            mock_build.assert_called_once()
            call_args = mock_build.call_args
            assert call_args[0][0] == "run-123_event_1"
            assert call_args[0][1] == "messages"
            assert call_args[0][2]["type"] == "messages_stream"
            assert call_args[0][2]["message_chunk"] == chunk
            assert call_args[0][2]["metadata"] == meta

            # flush 호출 확인
            mock_store.store_events.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_event_from_raw_values_stored_as_values_event_type(self):
        """#14: values 이벤트는 execution_values 타입으로 저장"""
        with (
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(("values", {"x": 1}), False),
            ),
            patch(
                "src.agent_server.services.streaming_service.build_sse_event",
                return_value="SSE_VAL",
            ) as mock_build,
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
        ):
            mock_store.store_events = AsyncMock()

            await self.service.store_event_from_raw("run-123", "run-123_event_1", ("values", {"x": 1}))

            mock_build.assert_called_once()
            call_args = mock_build.call_args
            assert call_args[0][1] == "values"
            assert call_args[0][2]["type"] == "execution_values"
            assert call_args[0][2]["chunk"] == {"x": 1}

    @pytest.mark.asyncio
    async def test_store_event_from_raw_updates_stored_as_values_event_type(self):
        """#14b: updates 이벤트도 values 타입으로 저장"""
        with (
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(("updates", {"y": 2}), False),
            ),
            patch(
                "src.agent_server.services.streaming_service.build_sse_event",
                return_value="SSE_UPD",
            ) as mock_build,
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
        ):
            mock_store.store_events = AsyncMock()

            await self.service.store_event_from_raw("run-123", "run-123_event_1", ("updates", {"y": 2}))

            mock_build.assert_called_once()
            call_args = mock_build.call_args
            assert call_args[0][1] == "values"  # updates도 values로 저장

    @pytest.mark.asyncio
    async def test_store_event_from_raw_end_forces_flush(self):
        """#15: end 이벤트는 force=True로 flush"""
        with (
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(
                    ("end", {"status": "completed", "final_output": 123}),
                    False,
                ),
            ),
            patch(
                "src.agent_server.services.streaming_service.build_sse_event",
                return_value="SSE_END",
            ) as mock_build,
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
        ):
            mock_store.store_events = AsyncMock()
            # batch size를 크게 설정해도 end는 force flush
            self.service._storage_batch_size = 100

            await self.service.store_event_from_raw(
                "run-123",
                "run-123_event_1",
                ("end", {"status": "completed", "final_output": 123}),
            )

            mock_build.assert_called_once()
            call_args = mock_build.call_args
            assert call_args[0][1] == "end"
            assert call_args[0][2]["type"] == "run_complete"
            assert call_args[0][2]["status"] == "completed"
            assert call_args[0][2]["final_output"] == 123

            # force flush 발생
            mock_store.store_events.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_event_from_raw_skips_when_interrupt_processing_requests_skip(
        self,
    ):
        """#16: should_skip=True면 저장 안함"""
        with (
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(("updates", {}), True),  # should_skip=True
            ),
            patch("src.agent_server.services.streaming_service.build_sse_event") as mock_build,
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
        ):
            mock_store.store_events = AsyncMock()

            await self.service.store_event_from_raw("run-123", "run-123_event_1", ("updates", {}))

            mock_build.assert_not_called()
            mock_store.store_events.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_store_event_from_raw_3_element_tuple_extracts_node_path(self):
        """#22: 3-element tuple (node_path, stream_mode, payload) 처리"""
        chunk = {"content": "Hi"}
        meta = {"node": "chatbot"}

        with (
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(("nodepath", "messages", (chunk, meta)), False),
            ),
            patch(
                "src.agent_server.services.streaming_service.build_sse_event",
                return_value="SSE_MSG",
            ) as mock_build,
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
        ):
            mock_store.store_events = AsyncMock()

            await self.service.store_event_from_raw(
                "run-123",
                "run-123_event_1",
                ("nodepath", "messages", (chunk, meta)),
            )

            mock_build.assert_called_once()
            call_args = mock_build.call_args
            # 3-element tuple: (node_path, stream_mode, payload)
            assert call_args[0][2]["node_path"] == "nodepath"

    @pytest.mark.asyncio
    async def test_store_event_from_raw_single_value_defaults_to_values_mode(self):
        """#23: 튜플이 아닌 단일 값은 values 모드로 처리"""
        single_value = {"key": "val"}

        with (
            patch.object(
                self.service,
                "_process_interrupt_updates",
                return_value=(single_value, False),  # 단일 dict
            ),
            patch(
                "src.agent_server.services.streaming_service.build_sse_event",
                return_value="SSE_VAL",
            ) as mock_build,
            patch("src.agent_server.services.streaming_service.event_store") as mock_store,
        ):
            mock_store.store_events = AsyncMock()

            await self.service.store_event_from_raw("run-123", "run-123_event_1", single_value)

            mock_build.assert_called_once()
            call_args = mock_build.call_args
            assert call_args[0][1] == "values"
            assert call_args[0][2]["chunk"] == single_value


# =============================================================================
# TestSignalRunEvents - #17, #24
# =============================================================================
class TestSignalRunEvents:
    """signal_run_cancelled, signal_run_error 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_signal_run_cancelled_puts_end_event_and_cleans_broker(self):
        """#17: signal_run_cancelled는 end 이벤트 전송 후 브로커 정리"""
        broker = make_fake_broker()

        with (
            patch(
                "src.agent_server.services.streaming_service.generate_event_id",
                return_value="run-123_event_1",
            ),
            patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm,
        ):
            mock_bm.get_or_create_broker.return_value = broker

            await self.service.signal_run_cancelled("run-123")

            # event_counters 증가 확인
            assert self.service.event_counters["run-123"] == 1

            # broker.put 호출 확인
            broker.put.assert_awaited_once_with("run-123_event_1", ("end", {"status": "cancelled"}))

            # cleanup_broker 호출 확인
            mock_bm.cleanup_broker.assert_called_once_with("run-123")

    @pytest.mark.asyncio
    async def test_signal_run_error_puts_end_event_with_error_and_cleans_broker(self):
        """#24: signal_run_error는 에러 메시지 포함한 end 이벤트 전송"""
        broker = make_fake_broker()

        with (
            patch(
                "src.agent_server.services.streaming_service.generate_event_id",
                return_value="run-123_event_1",
            ),
            patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm,
        ):
            mock_bm.get_or_create_broker.return_value = broker

            await self.service.signal_run_error("run-123", "Something went wrong")

            # event_counters 증가 확인
            assert self.service.event_counters["run-123"] == 1

            # broker.put 호출 확인 - error 포함
            broker.put.assert_awaited_once_with(
                "run-123_event_1",
                ("end", {"status": "failed", "error": "Something went wrong"}),
            )

            # cleanup_broker 호출 확인
            mock_bm.cleanup_broker.assert_called_once_with("run-123")


# =============================================================================
# TestRunControl - #18, #25
# =============================================================================
class TestRunControl:
    """cancel_run, interrupt_run 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_cancel_run_success_returns_true(self):
        """#18a: cancel_run 성공 시 True 반환"""
        with (
            patch.object(self.service, "signal_run_cancelled", new_callable=AsyncMock) as mock_signal,
            patch.object(self.service, "_update_run_status", new_callable=AsyncMock) as mock_update,
        ):
            result = await self.service.cancel_run("run-123")

            assert result is True
            mock_signal.assert_awaited_once_with("run-123")
            mock_update.assert_awaited_once_with("run-123", "cancelled")

    @pytest.mark.asyncio
    async def test_interrupt_run_success_returns_true(self):
        """#18b: interrupt_run 성공 시 True 반환"""
        with (
            patch.object(self.service, "signal_run_error", new_callable=AsyncMock) as mock_signal,
            patch.object(self.service, "_update_run_status", new_callable=AsyncMock) as mock_update,
        ):
            result = await self.service.interrupt_run("run-123")

            assert result is True
            mock_signal.assert_awaited_once_with("run-123", "Run was interrupted")
            mock_update.assert_awaited_once_with("run-123", "interrupted")

    @pytest.mark.asyncio
    async def test_cancel_run_returns_false_on_exception(self):
        """#25: cancel_run 예외 발생 시 False 반환"""
        with patch.object(
            self.service,
            "signal_run_cancelled",
            new_callable=AsyncMock,
            side_effect=Exception("db error"),
        ):
            result = await self.service.cancel_run("run-123")

            assert result is False

    @pytest.mark.asyncio
    async def test_interrupt_run_returns_false_on_exception(self):
        """#25b: interrupt_run 예외 발생 시 False 반환"""
        with patch.object(
            self.service,
            "signal_run_error",
            new_callable=AsyncMock,
            side_effect=Exception("db error"),
        ):
            result = await self.service.interrupt_run("run-123")

            assert result is False


# =============================================================================
# TestCleanupRun - #19
# =============================================================================
class TestCleanupRun:
    """cleanup_run 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_cleanup_run_flushes_batch_and_cleans_broker(self):
        """#19: cleanup_run은 batch flush 후 브로커 정리"""
        with (
            patch.object(self.service, "_flush_storage_batch", new_callable=AsyncMock) as mock_flush,
            patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm,
        ):
            await self.service.cleanup_run("run-123")

            mock_flush.assert_awaited_once_with("run-123", force=True)
            mock_bm.cleanup_broker.assert_called_once_with("run-123")


# =============================================================================
# TestIsRunStreaming - #20-21
# =============================================================================
class TestIsRunStreaming:
    """is_run_streaming 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    def test_is_run_streaming_returns_true_when_broker_active(self):
        """#20: 브로커가 존재하고 is_finished=False면 True"""
        broker = make_fake_broker(is_finished=False)

        with patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm:
            mock_bm.get_broker.return_value = broker

            result = self.service.is_run_streaming("run-123")

            assert result is True

    def test_is_run_streaming_returns_false_when_no_broker(self):
        """#21a: 브로커가 없으면 False"""
        with patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm:
            mock_bm.get_broker.return_value = None

            result = self.service.is_run_streaming("run-123")

            assert result is False

    def test_is_run_streaming_returns_false_when_broker_finished(self):
        """#21b: 브로커가 finished 상태면 False"""
        broker = make_fake_broker(is_finished=True)

        with patch("src.agent_server.services.streaming_service.broker_manager") as mock_bm:
            mock_bm.get_broker.return_value = broker

            result = self.service.is_run_streaming("run-123")

            assert result is False


# =============================================================================
# TestFlushStorageBatch - 추가 테스트
# =============================================================================
class TestFlushStorageBatch:
    """_flush_storage_batch 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_flush_storage_batch_does_nothing_when_empty(self):
        """배치가 비어있으면 아무것도 안함"""
        with patch("src.agent_server.services.streaming_service.event_store") as mock_store:
            mock_store.store_events = AsyncMock()

            await self.service._flush_storage_batch("run-123")

            mock_store.store_events.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_flush_storage_batch_does_not_flush_when_under_batch_size(self):
        """배치 크기 미만이면 flush 안함 (force=False)"""
        self.service._storage_batch_size = 10
        self.service._storage_batches["run-123"] = ["event1", "event2"]

        with patch("src.agent_server.services.streaming_service.event_store") as mock_store:
            mock_store.store_events = AsyncMock()

            await self.service._flush_storage_batch("run-123", force=False)

            mock_store.store_events.assert_not_awaited()
            # 배치 유지
            assert len(self.service._storage_batches["run-123"]) == 2

    @pytest.mark.asyncio
    async def test_flush_storage_batch_flushes_when_force_true(self):
        """force=True면 배치 크기 상관없이 flush"""
        self.service._storage_batch_size = 10
        self.service._storage_batches["run-123"] = ["event1", "event2"]

        with patch("src.agent_server.services.streaming_service.event_store") as mock_store:
            mock_store.store_events = AsyncMock()

            await self.service._flush_storage_batch("run-123", force=True)

            mock_store.store_events.assert_awaited_once_with("run-123", ["event1", "event2"])
            # 배치 비워짐
            assert self.service._storage_batches["run-123"] == []

    @pytest.mark.asyncio
    async def test_flush_storage_batch_flushes_when_batch_size_reached(self):
        """배치 크기 도달하면 flush"""
        self.service._storage_batch_size = 2
        self.service._storage_batches["run-123"] = ["event1", "event2"]

        with patch("src.agent_server.services.streaming_service.event_store") as mock_store:
            mock_store.store_events = AsyncMock()

            await self.service._flush_storage_batch("run-123", force=False)

            mock_store.store_events.assert_awaited_once()
            assert self.service._storage_batches["run-123"] == []


# =============================================================================
# TestNextEventCounter - 추가 테스트
# =============================================================================
class TestNextEventCounter:
    """_next_event_counter 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    def test_next_event_counter_updates_counter_when_sequence_is_higher(self):
        """시퀀스가 더 크면 카운터 업데이트"""
        self.service.event_counters["run-123"] = 5

        result = self.service._next_event_counter("run-123", "run-123_event_10")

        assert result == 10
        assert self.service.event_counters["run-123"] == 10

    def test_next_event_counter_returns_current_when_sequence_is_lower(self):
        """시퀀스가 더 작으면 현재 카운터 유지"""
        self.service.event_counters["run-123"] = 15

        result = self.service._next_event_counter("run-123", "run-123_event_10")

        assert result == 15
        assert self.service.event_counters["run-123"] == 15

    def test_next_event_counter_handles_invalid_event_id_gracefully(self):
        """잘못된 event_id 형식은 현재 카운터 반환"""
        self.service.event_counters["run-123"] = 5

        result = self.service._next_event_counter("run-123", "invalid-format")

        assert result == 5


# =============================================================================
# TestCancelBackgroundTask - 추가 테스트
# =============================================================================
class TestCancelBackgroundTask:
    """_cancel_background_task 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    def test_cancel_background_task_cancels_active_task(self):
        """활성 태스크가 있으면 취소"""
        mock_task = MagicMock()
        mock_task.done.return_value = False

        # active_runs는 api.runs에서 lazy import됨
        with patch(
            "src.agent_server.api.runs.active_runs",
            {"run-123": mock_task},
        ):
            self.service._cancel_background_task("run-123")

            mock_task.cancel.assert_called_once()

    def test_cancel_background_task_does_nothing_when_task_done(self):
        """태스크가 이미 완료되었으면 취소 안함"""
        mock_task = MagicMock()
        mock_task.done.return_value = True

        with patch(
            "src.agent_server.api.runs.active_runs",
            {"run-123": mock_task},
        ):
            self.service._cancel_background_task("run-123")

            mock_task.cancel.assert_not_called()

    def test_cancel_background_task_handles_missing_task(self):
        """태스크가 없으면 예외 없이 통과"""
        with patch("src.agent_server.api.runs.active_runs", {}):
            # 예외 발생 안함
            self.service._cancel_background_task("run-123")

    def test_cancel_background_task_handles_exception_gracefully(self):
        """예외 발생 시 경고 로그만 출력 (예외 전파 안함)"""
        mock_runs = MagicMock()
        mock_runs.get.side_effect = RuntimeError("unexpected error")

        with patch("src.agent_server.api.runs.active_runs", mock_runs):
            self.service._cancel_background_task("run-123")


# =============================================================================
# TestConvertRawToSSE - 추가 테스트
# =============================================================================
class TestConvertRawToSSE:
    """_convert_raw_to_sse 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    @pytest.mark.asyncio
    async def test_convert_raw_to_sse_delegates_to_event_converter(self):
        """EventConverter.convert_raw_to_sse에 위임"""
        with patch.object(
            self.service.event_converter, "convert_raw_to_sse", return_value="SSE_EVENT"
        ) as mock_conv:
            result = await self.service._convert_raw_to_sse("event-123", ("values", {"x": 1}))

            assert result == "SSE_EVENT"
            mock_conv.assert_called_once_with("event-123", ("values", {"x": 1}))


# =============================================================================
# TestStoredEventToSSE - 추가 테스트
# =============================================================================
class TestStoredEventToSSE:
    """_stored_event_to_sse 메서드 테스트"""

    def setup_method(self):
        self.service = StreamingService()

    def test_stored_event_to_sse_delegates_to_event_converter(self):
        """EventConverter.convert_stored_to_sse에 위임"""
        stored_event = make_fake_stored_event()

        with patch.object(
            self.service.event_converter,
            "convert_stored_to_sse",
            return_value="SSE_STORED",
        ) as mock_conv:
            result = self.service._stored_event_to_sse("run-123", stored_event)

            assert result == "SSE_STORED"
            mock_conv.assert_called_once_with(stored_event, "run-123")
