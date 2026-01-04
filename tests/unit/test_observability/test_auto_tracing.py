"""Unit tests for auto_tracing module.

Tests cover:
1. OTEL disabled - zero overhead (no wrapping)
2. OTEL enabled - span creation and attributes
3. Method exclusion logic (_prefix, __trace_exclude__)
4. Async/sync method handling
5. Exception handling and error recording
6. Return value and metadata preservation
"""

import asyncio
from unittest.mock import MagicMock, patch, call

import pytest


class TestTracedService:
    """Test TracedService base class."""

    def test_subclass_methods_not_wrapped_when_otel_disabled(self):
        """Test that methods are not wrapped when OTEL is disabled."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def public_method(self):
                    return "result"

            service = TestService()
            result = service.public_method()
            assert result == "result"
            assert service.public_method.__name__ == "public_method"

    def test_private_methods_excluded(self):
        """Test that private methods (starting with _) are not wrapped."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def _private_method(self):
                    return "private"

                def public_method(self):
                    return "public"

            service = TestService()
            assert service._private_method() == "private"

    def test_trace_exclude_respected(self):
        """Test that methods in __trace_exclude__ are not wrapped."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                __trace_exclude__ = ["excluded_method"]

                def excluded_method(self):
                    return "excluded"

                def traced_method(self):
                    return "traced"

            service = TestService()
            assert service.excluded_method() == "excluded"


class TestTracedServiceDecorator:
    """Test @traced_service class decorator."""

    def test_decorator_works_like_inheritance(self):
        """Test that @traced_service behaves like TracedService inheritance."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            @auto_tracing.traced_service
            class TestService:
                def my_method(self):
                    return "result"

            service = TestService()
            result = service.my_method()
            assert result == "result"


class TestExtractTraceAttributes:
    """Test _extract_trace_attributes function."""

    def test_extracts_assistant_id(self):
        """Test that assistant_id is extracted from arguments."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, assistant_id: str):
            pass

        attrs = _extract_trace_attributes(test_func, (None, "asst-123"), {})
        assert attrs.get("service.assistant_id") == "asst-123"

    def test_extracts_thread_id(self):
        """Test that thread_id is extracted from arguments."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, thread_id: str):
            pass

        attrs = _extract_trace_attributes(test_func, (None, "thread-456"), {})
        assert attrs.get("service.thread_id") == "thread-456"

    def test_extracts_from_kwargs(self):
        """Test that attributes are extracted from keyword arguments."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, run_id: str = None):
            pass

        attrs = _extract_trace_attributes(test_func, (None,), {"run_id": "run-789"})
        assert attrs.get("service.run_id") == "run-789"

    def test_skips_none_values(self):
        """Test that None values are not included in attributes."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, assistant_id: str = None):
            pass

        attrs = _extract_trace_attributes(test_func, (None,), {"assistant_id": None})
        assert "service.assistant_id" not in attrs

    def test_extracts_multiple_attributes(self):
        """Test extracting multiple attributes at once."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, assistant_id: str, thread_id: str, run_id: str):
            pass

        attrs = _extract_trace_attributes(test_func, (None, "asst-123", "thread-456", "run-789"), {})
        assert attrs.get("service.assistant_id") == "asst-123"
        assert attrs.get("service.thread_id") == "thread-456"
        assert attrs.get("service.run_id") == "run-789"

    def test_extracts_graph_id(self):
        """Test that graph_id is extracted."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, graph_id: str):
            pass

        attrs = _extract_trace_attributes(test_func, (None, "my-graph"), {})
        assert attrs.get("service.graph_id") == "my-graph"

    def test_extracts_user_id(self):
        """Test that user_id is extracted."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, user_id: str):
            pass

        attrs = _extract_trace_attributes(test_func, (None, "user-123"), {})
        assert attrs.get("service.user_id") == "user-123"

    def test_extracts_namespace(self):
        """Test that namespace is extracted."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, namespace: str):
            pass

        attrs = _extract_trace_attributes(test_func, (None, "my-namespace"), {})
        assert attrs.get("service.namespace") == "my-namespace"

    def test_extracts_limit_and_offset(self):
        """Test that limit and offset are extracted."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        def test_func(self, limit: int, offset: int):
            pass

        attrs = _extract_trace_attributes(test_func, (None, 10, 20), {})
        assert attrs.get("service.limit") == "10"
        assert attrs.get("service.offset") == "20"

    def test_handles_invalid_signature(self):
        """Test graceful handling of functions without proper signature."""
        from src.agent_server.observability.auto_tracing import _extract_trace_attributes

        # Built-in functions don't have inspectable signatures
        attrs = _extract_trace_attributes(len, ("test",), {})
        assert attrs == {}


class TestShouldTraceMethod:
    """Test _should_trace_method function."""

    def test_excludes_private_methods(self):
        """Test that private methods are excluded."""
        from src.agent_server.observability.auto_tracing import _should_trace_method

        def _private():
            pass

        assert _should_trace_method("_private", _private, set()) is False

    def test_excludes_dunder_methods(self):
        """Test that dunder methods are excluded."""
        from src.agent_server.observability.auto_tracing import _should_trace_method

        def __init__():
            pass

        assert _should_trace_method("__init__", __init__, set()) is False

    def test_excludes_explicitly_excluded(self):
        """Test that methods in exclude_set are excluded."""
        from src.agent_server.observability.auto_tracing import _should_trace_method

        def my_method():
            pass

        assert _should_trace_method("my_method", my_method, {"my_method"}) is False

    def test_includes_public_methods(self):
        """Test that public methods are included."""
        from src.agent_server.observability.auto_tracing import _should_trace_method

        def public_method():
            pass

        assert _should_trace_method("public_method", public_method, set()) is True

    def test_excludes_non_callable(self):
        """Test that non-callable attributes are excluded."""
        from src.agent_server.observability.auto_tracing import _should_trace_method

        assert _should_trace_method("attribute", "not_callable", set()) is False


class TestAsyncMethodWrapping:
    """Test async method wrapping."""

    @pytest.mark.asyncio
    async def test_async_method_works(self):
        """Test that async methods work correctly when wrapped."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                async def async_method(self, value: int) -> int:
                    await asyncio.sleep(0)
                    return value * 2

            service = TestService()
            result = await service.async_method(21)
            assert result == 42

    @pytest.mark.asyncio
    async def test_async_method_propagates_exception(self):
        """Test that exceptions propagate correctly in async methods."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                async def failing_method(self):
                    raise ValueError("Async error")

            service = TestService()
            with pytest.raises(ValueError, match="Async error"):
                await service.failing_method()


class TestSyncMethodWrapping:
    """Test sync method wrapping."""

    def test_sync_method_works(self):
        """Test that sync methods work correctly when wrapped."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def sync_method(self, value: int) -> int:
                    return value * 2

            service = TestService()
            result = service.sync_method(21)
            assert result == 42

    def test_sync_method_propagates_exception(self):
        """Test that exceptions propagate correctly in sync methods."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def failing_method(self):
                    raise ValueError("Sync error")

            service = TestService()
            with pytest.raises(ValueError, match="Sync error"):
                service.failing_method()

    def test_preserves_function_metadata(self):
        """Test that wrapper preserves function metadata."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def my_method(self):
                    """My docstring"""
                    pass

            service = TestService()
            assert service.my_method.__name__ == "my_method"


class TestOtelEnabledSpanCreation:
    """Test span creation when OTEL is enabled.

    These tests use _wrap_method directly to verify span behavior,
    since TracedService.__init_subclass__ instrumentation happens at
    class definition time and is difficult to mock via reload.
    """

    def test_sync_method_creates_span_via_wrap_method(self):
        """Test that sync methods create spans with correct attributes via _wrap_method."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer):
            from src.agent_server.observability.auto_tracing import _wrap_method

            def get_item(self, assistant_id: str) -> str:
                return f"item-{assistant_id}"

            wrapped = _wrap_method(get_item, "TestService")
            result = wrapped(None, "asst-123")

            # Verify return value
            assert result == "item-asst-123"

            # Verify span was created with correct name
            mock_tracer.start_as_current_span.assert_called_with("service.TestService.get_item")

            # Verify base attributes were set
            mock_span.set_attribute.assert_any_call("service.name", "TestService")
            mock_span.set_attribute.assert_any_call("service.method", "get_item")
            mock_span.set_attribute.assert_any_call("code.function", "get_item")

    @pytest.mark.asyncio
    async def test_async_method_creates_span_via_wrap_method(self):
        """Test that async methods create spans with correct attributes via _wrap_method."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer):
            from src.agent_server.observability.auto_tracing import _wrap_method

            async def get_thread(self, thread_id: str) -> str:
                await asyncio.sleep(0)
                return f"thread-{thread_id}"

            wrapped = _wrap_method(get_thread, "TestService")
            result = await wrapped(None, "thread-456")

            # Verify return value
            assert result == "thread-thread-456"

            # Verify span was created
            mock_tracer.start_as_current_span.assert_called_with("service.TestService.get_thread")

            # Verify base attributes were set
            mock_span.set_attribute.assert_any_call("service.name", "TestService")
            mock_span.set_attribute.assert_any_call("service.method", "get_thread")

    def test_span_extracts_traced_attributes_via_wrap_method(self):
        """Test that span attributes are extracted from method arguments."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
            patch("src.agent_server.observability.auto_tracing._set_span_attributes") as mock_set_attrs,
        ):
            from src.agent_server.observability.auto_tracing import _wrap_method

            def create_run(self, assistant_id: str, thread_id: str, run_id: str) -> str:
                return "created"

            wrapped = _wrap_method(create_run, "TestService")
            wrapped(None, "asst-1", "thread-2", "run-3")

            # Verify _set_span_attributes was called with extracted attributes
            mock_set_attrs.assert_called()
            call_args = mock_set_attrs.call_args
            attrs = call_args[0][1]  # Second argument is the attributes dict
            assert attrs.get("service.assistant_id") == "asst-1"
            assert attrs.get("service.thread_id") == "thread-2"
            assert attrs.get("service.run_id") == "run-3"

    def test_instrument_class_wraps_methods_when_enabled(self):
        """Test that _instrument_class wraps methods when OTEL is enabled."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True),
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
        ):
            from src.agent_server.observability.auto_tracing import _instrument_class

            class OriginalClass:
                def my_method(self):
                    return "original"

            original_method = OriginalClass.my_method

            # Instrument the class
            result_class = _instrument_class(OriginalClass)

            # Method should be wrapped (different function)
            assert OriginalClass.my_method is not original_method

            # But should still work and trigger tracer
            instance = OriginalClass()
            result = instance.my_method()
            assert result == "original"
            mock_tracer.start_as_current_span.assert_called_with("service.OriginalClass.my_method")


class TestOtelEnabledErrorHandling:
    """Test error handling when OTEL is enabled.

    These tests use _wrap_method directly to verify error handling behavior.
    """

    def test_sync_exception_records_error_on_span(self):
        """Test that sync exceptions are recorded on span."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
            patch("src.agent_server.observability.auto_tracing._set_span_error_status") as mock_error_status,
        ):
            from src.agent_server.observability.auto_tracing import _wrap_method

            def failing_method(self):
                raise ValueError("Test error")

            wrapped = _wrap_method(failing_method, "TestService")

            with pytest.raises(ValueError, match="Test error"):
                wrapped(None)

            # Verify exception was recorded
            mock_span.record_exception.assert_called_once()
            recorded_exception = mock_span.record_exception.call_args[0][0]
            assert isinstance(recorded_exception, ValueError)
            assert str(recorded_exception) == "Test error"

            # Verify error attribute was set
            mock_span.set_attribute.assert_any_call("service.error", True)

            # Verify error status was set
            mock_error_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_exception_records_error_on_span(self):
        """Test that async exceptions are recorded on span."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
            patch("src.agent_server.observability.auto_tracing._set_span_error_status") as mock_error_status,
        ):
            from src.agent_server.observability.auto_tracing import _wrap_method

            async def async_failing(self):
                await asyncio.sleep(0)
                raise RuntimeError("Async failure")

            wrapped = _wrap_method(async_failing, "TestService")

            with pytest.raises(RuntimeError, match="Async failure"):
                await wrapped(None)

            # Verify exception was recorded
            mock_span.record_exception.assert_called_once()
            mock_span.set_attribute.assert_any_call("service.error", True)
            mock_error_status.assert_called_once()

    def test_ok_status_set_on_success(self):
        """Test that OK status is set on successful execution."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
            patch("src.agent_server.observability.auto_tracing._set_span_ok_status") as mock_ok_status,
        ):
            from src.agent_server.observability.auto_tracing import _wrap_method

            def success_method(self) -> str:
                return "success"

            wrapped = _wrap_method(success_method, "TestService")
            result = wrapped(None)

            assert result == "success"
            mock_ok_status.assert_called_once_with(mock_span)

    @pytest.mark.asyncio
    async def test_async_ok_status_set_on_success(self):
        """Test that OK status is set on successful async execution."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
            patch("src.agent_server.observability.auto_tracing._set_span_ok_status") as mock_ok_status,
        ):
            from src.agent_server.observability.auto_tracing import _wrap_method

            async def async_success(self) -> str:
                await asyncio.sleep(0)
                return "async success"

            wrapped = _wrap_method(async_success, "TestService")
            result = await wrapped(None)

            assert result == "async success"
            mock_ok_status.assert_called_once_with(mock_span)


class TestStaticAndClassMethods:
    """Test that static and class methods are excluded from tracing."""

    def test_staticmethod_excluded(self):
        """Test that staticmethod is not wrapped."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                @staticmethod
                def static_method():
                    return "static"

            # Should work without error
            result = TestService.static_method()
            assert result == "static"

    def test_classmethod_excluded(self):
        """Test that classmethod is not wrapped."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                @classmethod
                def class_method(cls):
                    return f"class-{cls.__name__}"

            # Should work without error
            result = TestService.class_method()
            assert result == "class-TestService"


class TestReturnValuePreservation:
    """Test that return values are preserved correctly."""

    def test_complex_return_value_preserved(self):
        """Test that complex return values are preserved."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True),
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
        ):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def get_complex(self) -> dict:
                    return {
                        "id": "123",
                        "items": [1, 2, 3],
                        "nested": {"key": "value"},
                    }

            service = TestService()
            result = service.get_complex()

            assert result == {
                "id": "123",
                "items": [1, 2, 3],
                "nested": {"key": "value"},
            }

    def test_none_return_value_preserved(self):
        """Test that None return values are preserved."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True),
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
        ):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def void_method(self) -> None:
                    pass

            service = TestService()
            result = service.void_method()

            assert result is None


class TestDocstringPreservation:
    """Test that docstrings are preserved."""

    def test_docstring_preserved_otel_disabled(self):
        """Test docstring preservation when OTEL is disabled."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def documented_method(self):
                    """This is my docstring."""
                    pass

            service = TestService()
            assert service.documented_method.__doc__ == "This is my docstring."

    def test_docstring_preserved_otel_enabled(self):
        """Test docstring preservation when OTEL is enabled."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True),
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
        ):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def documented_method(self):
                    """This is my docstring."""
                    pass

            service = TestService()
            assert service.documented_method.__doc__ == "This is my docstring."


class TestInstrumentClass:
    """Test _instrument_class function directly."""

    def test_returns_class_unmodified_when_disabled(self):
        """Test that class is returned unmodified when OTEL disabled."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from src.agent_server.observability.auto_tracing import _instrument_class

            class OriginalClass:
                def my_method(self):
                    return "original"

            original_method = OriginalClass.my_method
            result_class = _instrument_class(OriginalClass)

            # Class should be the same
            assert result_class is OriginalClass
            # Method should be unchanged
            assert OriginalClass.my_method is original_method

    def test_wraps_methods_when_enabled(self):
        """Test that methods are wrapped when OTEL enabled."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with (
            patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=True),
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
        ):
            from src.agent_server.observability.auto_tracing import _instrument_class

            class OriginalClass:
                def my_method(self):
                    return "original"

            original_method = OriginalClass.my_method
            result_class = _instrument_class(OriginalClass)

            # Class should be the same reference
            assert result_class is OriginalClass
            # Method should be wrapped (different function)
            assert OriginalClass.my_method is not original_method
            # But should still work and trigger tracer
            instance = OriginalClass()
            result = instance.my_method()
            assert result == "original"
            mock_tracer.start_as_current_span.assert_called_with("service.OriginalClass.my_method")


class TestWrapMethod:
    """Test _wrap_method function directly."""

    def test_wrap_sync_method(self):
        """Test wrapping a sync method."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer):
            from src.agent_server.observability.auto_tracing import _wrap_method

            def original(self, x: int) -> int:
                return x * 2

            wrapped = _wrap_method(original, "TestService")
            result = wrapped(None, 21)

            assert result == 42
            mock_tracer.start_as_current_span.assert_called_with("service.TestService.original")

    @pytest.mark.asyncio
    async def test_wrap_async_method(self):
        """Test wrapping an async method."""
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(return_value=mock_span)
        mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(return_value=None)

        with patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer):
            from src.agent_server.observability.auto_tracing import _wrap_method

            async def original(self, x: int) -> int:
                await asyncio.sleep(0)
                return x * 2

            wrapped = _wrap_method(original, "TestService")
            result = await wrapped(None, 21)

            assert result == 42
            mock_tracer.start_as_current_span.assert_called_with("service.TestService.original")


class TestMultipleInheritance:
    """Test behavior with multiple inheritance."""

    def test_multiple_inheritance_works(self):
        """Test that multiple inheritance works correctly."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class Mixin:
                def mixin_method(self):
                    return "mixin"

            class TestService(auto_tracing.TracedService, Mixin):
                def service_method(self):
                    return "service"

            service = TestService()
            assert service.mixin_method() == "mixin"
            assert service.service_method() == "service"


class TestZeroOverheadVerification:
    """Verify zero overhead when OTEL is disabled."""

    def test_method_is_original_function_when_disabled(self):
        """Test that methods are not wrapped when OTEL disabled (true zero overhead)."""
        with patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            def original_impl(self):
                return "original"

            class TestService(auto_tracing.TracedService):
                my_method = original_impl

            # The method should be the EXACT same function (not a wrapper)
            # This proves zero overhead - no wrapper function exists
            assert vars(TestService).get("my_method") is original_impl

    def test_no_tracer_calls_when_disabled(self):
        """Test that tracer is never called when OTEL disabled."""
        mock_tracer = MagicMock()

        with (
            patch("src.agent_server.observability.auto_tracing.is_otel_enabled", return_value=False),
            patch("src.agent_server.observability.auto_tracing.get_tracer", return_value=mock_tracer),
        ):
            from importlib import reload

            import src.agent_server.observability.auto_tracing as auto_tracing

            reload(auto_tracing)

            class TestService(auto_tracing.TracedService):
                def my_method(self):
                    return "result"

            service = TestService()
            result = service.my_method()

            assert result == "result"
            # Tracer should never be called
            mock_tracer.start_as_current_span.assert_not_called()
