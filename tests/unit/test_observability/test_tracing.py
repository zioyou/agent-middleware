"""Unit tests for tracing decorators module."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest


class TestTraceFunction:
    """Test trace_function decorator."""

    def test_sync_function_decoration(self):
        """Test that sync functions work correctly with trace_function."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="test_sync_op")
        def sync_function(x: int, y: int) -> int:
            return x + y

        result = sync_function(1, 2)
        assert result == 3

    def test_sync_function_preserves_metadata(self):
        """Test that decorator preserves function metadata."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="test_op")
        def my_function():
            """My docstring"""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring"

    @pytest.mark.asyncio
    async def test_async_function_decoration(self):
        """Test that async functions work correctly with trace_function."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="test_async_op")
        async def async_function(x: int, y: int) -> int:
            await asyncio.sleep(0)
            return x + y

        result = await async_function(2, 3)
        assert result == 5

    @pytest.mark.asyncio
    async def test_async_function_preserves_metadata(self):
        """Test that async decorator preserves function metadata."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function()
        async def my_async_function():
            """Async docstring"""
            pass

        assert my_async_function.__name__ == "my_async_function"
        assert my_async_function.__doc__ == "Async docstring"

    def test_sync_function_exception_propagates(self):
        """Test that exceptions propagate correctly through decorated sync function."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="failing_op")
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            failing_function()

    @pytest.mark.asyncio
    async def test_async_function_exception_propagates(self):
        """Test that exceptions propagate correctly through decorated async function."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="failing_async_op")
        async def failing_async_function():
            raise RuntimeError("Async error")

        with pytest.raises(RuntimeError, match="Async error"):
            await failing_async_function()

    def test_custom_attributes_passed(self):
        """Test that custom attributes are passed to the span."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="op_with_attrs", attributes={"key": "value", "count": 42})
        def function_with_attrs():
            return "success"

        result = function_with_attrs()
        assert result == "success"

    def test_default_span_name_uses_qualified_name(self):
        """Test that default span name uses module.qualname format."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function()  # No name specified
        def my_function():
            return True

        result = my_function()
        assert result is True


class TestTraceGraphExecution:
    """Test trace_graph_execution decorator."""

    def test_sync_graph_execution(self):
        """Test sync function with trace_graph_execution."""
        from src.agent_server.observability.tracing import trace_graph_execution

        @trace_graph_execution(graph_id="test_graph")
        def execute_graph(input_data: dict) -> dict:
            return {"result": input_data.get("value", 0) * 2}

        result = execute_graph({"value": 5})
        assert result == {"result": 10}

    @pytest.mark.asyncio
    async def test_async_graph_execution(self):
        """Test async function with trace_graph_execution."""
        from src.agent_server.observability.tracing import trace_graph_execution

        @trace_graph_execution(graph_id="async_graph")
        async def execute_async_graph(input_data: dict) -> dict:
            await asyncio.sleep(0)
            return {"result": "processed"}

        result = await execute_async_graph({"data": "test"})
        assert result == {"result": "processed"}

    @pytest.mark.asyncio
    async def test_kwargs_extraction(self):
        """Test that thread_id, run_id, assistant_id are extracted from kwargs."""
        from src.agent_server.observability.tracing import trace_graph_execution

        @trace_graph_execution(graph_id="test_graph")
        async def run_with_ids(thread_id: str = "", run_id: str = "", assistant_id: str = "") -> dict:
            return {
                "thread_id": thread_id,
                "run_id": run_id,
                "assistant_id": assistant_id,
            }

        result = await run_with_ids(thread_id="thread-123", run_id="run-456", assistant_id="asst-789")
        assert result["thread_id"] == "thread-123"
        assert result["run_id"] == "run-456"
        assert result["assistant_id"] == "asst-789"

    def test_exception_captures_error_info(self):
        """Test that exceptions add error attributes to span."""
        from src.agent_server.observability.tracing import trace_graph_execution

        @trace_graph_execution(graph_id="failing_graph")
        def failing_graph():
            raise ValueError("Graph execution failed")

        with pytest.raises(ValueError, match="Graph execution failed"):
            failing_graph()


class TestTraceServiceMethod:
    """Test trace_service_method decorator."""

    def test_sync_service_method(self):
        """Test sync method with trace_service_method."""
        from src.agent_server.observability.tracing import trace_service_method

        class TestService:
            @trace_service_method(service_name="TestService")
            def do_something(self, value: str) -> str:
                return f"processed: {value}"

        service = TestService()
        result = service.do_something("test")
        assert result == "processed: test"

    @pytest.mark.asyncio
    async def test_async_service_method(self):
        """Test async method with trace_service_method."""
        from src.agent_server.observability.tracing import trace_service_method

        class AsyncService:
            @trace_service_method(service_name="AsyncService")
            async def async_operation(self, data: dict) -> dict:
                await asyncio.sleep(0)
                return {"status": "completed", **data}

        service = AsyncService()
        result = await service.async_operation({"key": "value"})
        assert result == {"status": "completed", "key": "value"}

    def test_service_method_preserves_metadata(self):
        """Test that service method decorator preserves metadata."""
        from src.agent_server.observability.tracing import trace_service_method

        class MyService:
            @trace_service_method(service_name="MyService")
            def my_method(self):
                """Method documentation"""
                pass

        service = MyService()
        assert service.my_method.__name__ == "my_method"
        assert service.my_method.__doc__ == "Method documentation"

    def test_service_method_exception_propagates(self):
        """Test that exceptions propagate from decorated service methods."""
        from src.agent_server.observability.tracing import trace_service_method

        class FailingService:
            @trace_service_method(service_name="FailingService")
            def failing_method(self):
                raise RuntimeError("Service error")

        service = FailingService()
        with pytest.raises(RuntimeError, match="Service error"):
            service.failing_method()


class TestIsTracingEnabled:
    """Test is_tracing_enabled function."""

    def test_returns_false_when_otel_not_enabled(self):
        """Test that is_tracing_enabled returns False when OTEL not enabled."""
        import src.agent_server.observability.tracing as tracing_module

        with patch.object(tracing_module, "is_otel_enabled", return_value=False):
            assert tracing_module.is_tracing_enabled() is False

    def test_returns_true_when_otel_enabled(self):
        """Test that is_tracing_enabled returns True when OTEL enabled."""
        import src.agent_server.observability.tracing as tracing_module

        with patch.object(tracing_module, "is_otel_enabled", return_value=True):
            assert tracing_module.is_tracing_enabled() is True


class TestSetSpanAttributes:
    """Test _set_span_attributes helper function."""

    def test_sets_string_attribute(self):
        """Test setting string attributes on span."""
        from src.agent_server.observability.tracing import _set_span_attributes

        mock_span = MagicMock()
        _set_span_attributes(mock_span, {"key": "value"})
        mock_span.set_attribute.assert_called_with("key", "value")

    def test_sets_numeric_attributes(self):
        """Test setting numeric attributes on span."""
        from src.agent_server.observability.tracing import _set_span_attributes

        mock_span = MagicMock()
        _set_span_attributes(mock_span, {"int_key": 42, "float_key": 3.14})

        calls = mock_span.set_attribute.call_args_list
        assert any(call[0] == ("int_key", 42) for call in calls)
        assert any(call[0] == ("float_key", 3.14) for call in calls)

    def test_sets_boolean_attribute(self):
        """Test setting boolean attributes on span."""
        from src.agent_server.observability.tracing import _set_span_attributes

        mock_span = MagicMock()
        _set_span_attributes(mock_span, {"flag": True})
        mock_span.set_attribute.assert_called_with("flag", True)

    def test_converts_complex_types_to_string(self):
        """Test that complex types are converted to string."""
        from src.agent_server.observability.tracing import _set_span_attributes

        mock_span = MagicMock()
        _set_span_attributes(mock_span, {"complex": {"nested": "dict"}})
        mock_span.set_attribute.assert_called_with("complex", str({"nested": "dict"}))

    def test_handles_none_attributes(self):
        """Test that None attributes are handled gracefully."""
        from src.agent_server.observability.tracing import _set_span_attributes

        mock_span = MagicMock()
        _set_span_attributes(mock_span, None)
        mock_span.set_attribute.assert_not_called()

    def test_handles_list_of_primitives(self):
        """Test setting list attributes on span."""
        from src.agent_server.observability.tracing import _set_span_attributes

        mock_span = MagicMock()
        _set_span_attributes(mock_span, {"tags": ["a", "b", "c"]})
        mock_span.set_attribute.assert_called_with("tags", ["a", "b", "c"])

    def test_silently_handles_attribute_errors(self):
        """Test that attribute setting errors are silently ignored."""
        from src.agent_server.observability.tracing import _set_span_attributes

        mock_span = MagicMock()
        mock_span.set_attribute.side_effect = Exception("Set failed")

        # Should not raise
        _set_span_attributes(mock_span, {"key": "value"})


class TestNoOpBehavior:
    """Test that decorators work correctly when OTEL is disabled."""

    def test_trace_function_works_without_otel(self):
        """Test trace_function works when OTEL packages not installed."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="noop_test")
        def simple_function():
            return 42

        # Should work without errors even if OTEL is not initialized
        result = simple_function()
        assert result == 42

    @pytest.mark.asyncio
    async def test_async_trace_function_works_without_otel(self):
        """Test async trace_function works when OTEL not installed."""
        from src.agent_server.observability.tracing import trace_function

        @trace_function(name="async_noop_test")
        async def async_simple_function():
            return "async result"

        result = await async_simple_function()
        assert result == "async result"

    def test_trace_graph_execution_works_without_otel(self):
        """Test trace_graph_execution works when OTEL not initialized."""
        from src.agent_server.observability.tracing import trace_graph_execution

        @trace_graph_execution(graph_id="noop_graph")
        def graph_function():
            return {"data": "value"}

        result = graph_function()
        assert result == {"data": "value"}

    def test_trace_service_method_works_without_otel(self):
        """Test trace_service_method works when OTEL not initialized."""
        from src.agent_server.observability.tracing import trace_service_method

        class NoOpService:
            @trace_service_method(service_name="NoOpService")
            def method(self):
                return "method result"

        service = NoOpService()
        result = service.method()
        assert result == "method result"


class TestDecoratorChaining:
    """Test that decorators can be chained with other decorators."""

    def test_chain_with_staticmethod(self):
        """Test trace_function with staticmethod."""
        from src.agent_server.observability.tracing import trace_function

        class MyClass:
            @staticmethod
            @trace_function(name="static_op")
            def static_method(x: int) -> int:
                return x * 2

        result = MyClass.static_method(5)
        assert result == 10

    def test_chain_with_classmethod(self):
        """Test trace_function with classmethod."""
        from src.agent_server.observability.tracing import trace_function

        class MyClass:
            counter = 0

            @classmethod
            @trace_function(name="class_op")
            def class_method(cls) -> int:
                cls.counter += 1
                return cls.counter

        result = MyClass.class_method()
        assert result == 1
