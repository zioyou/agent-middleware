"""Integration tests for OpenTelemetry tracing.

These tests verify that tracing decorators produce actual spans
when OTEL is enabled. Run with:

    OTEL_ENABLED=true pytest tests/integration/test_otel_tracing.py -v

For visual inspection with Jaeger:
    docker compose --profile observability up -d jaeger
    # Then check http://localhost:16686
"""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def enable_otel():
    """Enable OTEL for the duration of the test."""
    with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
        import importlib

        from src.agent_server.observability import otel_integration

        importlib.reload(otel_integration)
        yield
        importlib.reload(otel_integration)


@pytest.fixture
def mock_tracer():
    """Create a mock tracer that captures spans."""
    spans = []

    class MockSpan:
        def __init__(self, name):
            self.name = name
            self.attributes = {}
            self.status = None
            self.events = []

        def set_attribute(self, key, value):
            self.attributes[key] = value

        def set_status(self, status):
            self.status = status

        def record_exception(self, exc):
            self.events.append(("exception", exc))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class MockTracer:
        def start_as_current_span(self, name, **kwargs):
            span = MockSpan(name)
            spans.append(span)
            return span

    mock = MagicMock()
    mock.start_as_current_span = MockTracer().start_as_current_span

    with patch(
        "src.agent_server.observability.tracing.get_tracer",
        return_value=mock,
    ):
        with patch(
            "src.agent_server.observability.tracing.is_otel_initialized",
            return_value=True,
        ):
            yield spans


class TestTraceFunctionIntegration:
    """Test trace_function decorator produces spans."""

    def test_sync_function_creates_span(self, mock_tracer):
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="test.sync_op")
        def sync_operation(x: int) -> int:
            return x * 2

        result = sync_operation(5)

        assert result == 10
        assert len(mock_tracer) == 1
        assert mock_tracer[0].name == "test.sync_op"

    @pytest.mark.asyncio
    async def test_async_function_creates_span(self, mock_tracer):
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="test.async_op")
        async def async_operation(x: int) -> int:
            return x * 3

        result = await async_operation(5)

        assert result == 15
        assert len(mock_tracer) == 1
        assert mock_tracer[0].name == "test.async_op"

    def test_custom_attributes_set_on_span(self, mock_tracer):
        from src.agent_server.observability.tracing import trace_function

        @trace_function(
            name="test.with_attrs",
            attributes={"custom.key": "custom_value", "custom.number": 42},
        )
        def operation_with_attrs():
            return "done"

        result = operation_with_attrs()

        assert result == "done"
        assert len(mock_tracer) == 1
        span = mock_tracer[0]
        assert span.attributes.get("custom.key") == "custom_value"
        assert span.attributes.get("custom.number") == 42


class TestTraceServiceMethodIntegration:
    """Test trace_service_method decorator produces spans with service info."""

    def test_service_method_span_name(self, mock_tracer):
        from src.agent_server.observability.tracing import trace_service_method

        class MyService:
            @trace_service_method(service_name="MyService")
            def do_work(self, data: str) -> str:
                return f"processed: {data}"

        svc = MyService()
        result = svc.do_work("input")

        assert result == "processed: input"
        assert len(mock_tracer) == 1
        assert mock_tracer[0].name == "service.MyService.do_work"
        assert mock_tracer[0].attributes.get("service.name") == "MyService"

    @pytest.mark.asyncio
    async def test_async_service_method_span(self, mock_tracer):
        from src.agent_server.observability.tracing import trace_service_method

        class AsyncService:
            @trace_service_method(service_name="AsyncService")
            async def async_work(self, value: int) -> int:
                return value + 100

        svc = AsyncService()
        result = await svc.async_work(50)

        assert result == 150
        assert len(mock_tracer) == 1
        assert mock_tracer[0].name == "service.AsyncService.async_work"
        assert mock_tracer[0].attributes.get("service.name") == "AsyncService"


class TestTraceGraphExecutionIntegration:
    """Test trace_graph_execution decorator for LangGraph operations."""

    @pytest.mark.asyncio
    async def test_graph_execution_span_attributes(self, mock_tracer):
        from src.agent_server.observability.tracing import trace_graph_execution

        @trace_graph_execution(graph_id="test_graph")
        async def execute_graph(input_data: dict, thread_id: str = None) -> dict:
            return {"result": "success", "input": input_data}

        result = await execute_graph({"query": "hello"}, thread_id="thread-123")

        assert result["result"] == "success"
        assert len(mock_tracer) == 1
        span = mock_tracer[0]
        assert span.name == "langgraph.execute.test_graph"
        assert span.attributes.get("langgraph.graph_id") == "test_graph"
        assert span.attributes.get("langgraph.thread_id") == "thread-123"


class TestRealServiceDecoratorApplication:
    """Verify decorators are properly applied to actual service classes."""

    def test_assistant_service_has_tracing(self):
        from src.agent_server.services.assistant_service import AssistantService

        methods_with_tracing = [
            "create_assistant",
            "get_assistant",
            "update_assistant",
            "delete_assistant",
            "list_assistants",
            "search_assistants",
            "get_assistant_schemas",
            "get_assistant_graph",
            "get_assistant_subgraphs",
        ]

        for method_name in methods_with_tracing:
            method = getattr(AssistantService, method_name)
            assert hasattr(method, "__wrapped__"), (
                f"{method_name} should have __wrapped__ attribute from decorator"
            )

    def test_langgraph_service_has_tracing(self):
        from src.agent_server.services.langgraph_service import LangGraphService

        methods_with_tracing = ["initialize", "get_graph"]

        for method_name in methods_with_tracing:
            method = getattr(LangGraphService, method_name)
            assert hasattr(method, "__wrapped__"), (
                f"{method_name} should have __wrapped__ attribute from decorator"
            )

    def test_streaming_service_has_tracing(self):
        from src.agent_server.services.streaming_service import StreamingService

        methods_with_tracing = [
            "put_to_broker",
            "store_event_from_raw",
            "stream_run_execution",
        ]

        for method_name in methods_with_tracing:
            method = getattr(StreamingService, method_name)
            assert hasattr(method, "__wrapped__"), (
                f"{method_name} should have __wrapped__ attribute from decorator"
            )


class TestNoOpWhenDisabled:
    """Verify tracing is no-op when OTEL is disabled."""

    def test_no_overhead_when_disabled(self):
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            from src.agent_server.observability.tracing import (
                is_tracing_enabled,
                trace_function,
            )

            call_count = 0

            @trace_function(name="test.noop")
            def simple_func():
                nonlocal call_count
                call_count += 1
                return 42

            result = simple_func()

            assert result == 42
            assert call_count == 1
            assert not is_tracing_enabled()
