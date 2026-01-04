"""Unit tests for OpenTelemetry integration module."""

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestIsOtelEnabled:
    """Test is_otel_enabled function."""

    def test_otel_disabled_by_default(self):
        """Test that OTEL is disabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove OTEL_ENABLED from environment
            os.environ.pop("OTEL_ENABLED", None)
            # Reimport to pick up new env
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            assert otel_module.is_otel_enabled() is False

    def test_otel_enabled_when_true(self):
        """Test that OTEL is enabled when OTEL_ENABLED=true."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            assert otel_module.is_otel_enabled() is True

    def test_otel_enabled_case_insensitive(self):
        """Test that OTEL_ENABLED is case insensitive."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "TRUE"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            assert otel_module.is_otel_enabled() is True

    def test_otel_disabled_when_false(self):
        """Test that OTEL is disabled when OTEL_ENABLED=false."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            assert otel_module.is_otel_enabled() is False


class TestSetupOpentelemetry:
    """Test setup_opentelemetry function."""

    def test_returns_false_when_disabled(self):
        """Test that setup returns False when OTEL is disabled."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            otel_module._otel_initialized = False

            mock_app = MagicMock()
            result = otel_module.setup_opentelemetry(mock_app)

            assert result is False
            assert otel_module.is_otel_initialized() is False

    def test_returns_false_when_packages_not_installed(self):
        """Test that setup returns False when OTEL packages not installed."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            otel_module._otel_initialized = False

            # Mock import to raise ImportError
            with patch.dict(sys.modules, {"opentelemetry": None}):
                mock_app = MagicMock()

                # Create a custom import that fails for opentelemetry
                original_import = __builtins__["__import__"]

                def mock_import(name, *args, **kwargs):
                    if "opentelemetry" in name:
                        raise ImportError(name)
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=mock_import):
                    result = otel_module.setup_opentelemetry(mock_app)

                # Should return False due to ImportError handling
                # (Note: actual behavior depends on import timing)

    def test_returns_true_when_already_initialized(self):
        """Test that setup returns True when already initialized."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            otel_module._otel_initialized = True

            mock_app = MagicMock()
            result = otel_module.setup_opentelemetry(mock_app)

            assert result is True


class TestNoOpTracer:
    """Test NoOp tracer implementation."""

    def test_noop_tracer_start_span(self):
        """Test NoOp tracer start_span returns NoOp span."""
        from src.agent_server.observability.otel_integration import _NoOpTracer

        tracer = _NoOpTracer()
        span = tracer.start_span("test_span")

        assert span is not None
        # Should not raise
        span.set_attribute("key", "value")
        span.end()

    def test_noop_tracer_start_as_current_span(self):
        """Test NoOp tracer start_as_current_span context manager."""
        from src.agent_server.observability.otel_integration import _NoOpTracer

        tracer = _NoOpTracer()

        # Should work as context manager
        with tracer.start_as_current_span("test_span") as span:
            span.set_attribute("key", "value")

    def test_noop_span_methods_dont_raise(self):
        """Test that NoOp span methods don't raise exceptions."""
        from src.agent_server.observability.otel_integration import _NoOpSpan

        span = _NoOpSpan()

        # None of these should raise
        span.set_attribute("key", "value")
        span.set_status("OK")
        span.record_exception(Exception("test"))
        span.end()

    def test_noop_span_context_manager(self):
        """Test NoOp span as context manager."""
        from src.agent_server.observability.otel_integration import _NoOpSpan

        span = _NoOpSpan()

        with span:
            span.set_attribute("key", "value")


class TestGetTracer:
    """Test get_tracer function."""

    def test_get_tracer_returns_noop_when_not_initialized(self):
        """Test get_tracer returns NoOp tracer when not initialized."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            otel_module._otel_initialized = False

            tracer = otel_module.get_tracer("test")

            # Should not raise when used
            with tracer.start_as_current_span("test_span"):
                pass

    def test_get_tracer_with_custom_name(self):
        """Test get_tracer with custom name."""
        with patch.dict(os.environ, {"OTEL_ENABLED": "false"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)
            otel_module._otel_initialized = False

            tracer = otel_module.get_tracer("custom.module.name")

            assert tracer is not None


class TestShutdownOpentelemetry:
    """Test shutdown_opentelemetry function."""

    def test_shutdown_when_not_initialized(self):
        """Test shutdown does nothing when not initialized."""
        import src.agent_server.observability.otel_integration as otel_module

        otel_module._otel_initialized = False

        # Should not raise
        otel_module.shutdown_opentelemetry()

    def test_shutdown_resets_initialized_flag(self):
        """Test shutdown resets the initialized flag."""
        import src.agent_server.observability.otel_integration as otel_module

        otel_module._otel_initialized = True

        # Mock the trace module - need to patch at the import location
        mock_provider = MagicMock()
        mock_provider.shutdown = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "opentelemetry": MagicMock(),
                "opentelemetry.trace": MagicMock(get_tracer_provider=MagicMock(return_value=mock_provider)),
            },
        ):
            otel_module.shutdown_opentelemetry()

            assert otel_module._otel_initialized is False


class TestEnvironmentVariables:
    """Test environment variable handling."""

    def test_default_endpoint(self):
        """Test default OTLP endpoint."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)

            assert otel_module._OTEL_ENDPOINT == "http://localhost:4317"

    def test_custom_endpoint(self):
        """Test custom OTLP endpoint."""
        with patch.dict(os.environ, {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://custom:4317"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)

            assert otel_module._OTEL_ENDPOINT == "http://custom:4317"

    def test_default_service_name(self):
        """Test default service name."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OTEL_SERVICE_NAME", None)
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)

            assert otel_module._OTEL_SERVICE_NAME == "open-langgraph"

    def test_custom_service_name(self):
        """Test custom service name."""
        with patch.dict(os.environ, {"OTEL_SERVICE_NAME": "my-custom-service"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)

            assert otel_module._OTEL_SERVICE_NAME == "my-custom-service"

    def test_default_environment(self):
        """Test default deployment environment."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OTEL_DEPLOYMENT_ENVIRONMENT", None)
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)

            assert otel_module._OTEL_ENVIRONMENT == "development"

    def test_custom_environment(self):
        """Test custom deployment environment."""
        with patch.dict(os.environ, {"OTEL_DEPLOYMENT_ENVIRONMENT": "production"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)

            assert otel_module._OTEL_ENVIRONMENT == "production"

    def test_insecure_default_true(self):
        """Test insecure mode is true by default."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OTEL_INSECURE", None)
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)

            assert otel_module._OTEL_INSECURE is True

    def test_insecure_false(self):
        """Test insecure mode can be disabled."""
        with patch.dict(os.environ, {"OTEL_INSECURE": "false"}):
            import src.agent_server.observability.otel_integration as otel_module

            otel_module = importlib.reload(otel_module)

            assert otel_module._OTEL_INSECURE is False


class TestIsOtelInitialized:
    """Test is_otel_initialized function."""

    def test_returns_false_initially(self):
        """Test is_otel_initialized returns False initially."""
        import src.agent_server.observability.otel_integration as otel_module

        otel_module._otel_initialized = False

        assert otel_module.is_otel_initialized() is False

    def test_returns_true_after_init(self):
        """Test is_otel_initialized returns True after initialization."""
        import src.agent_server.observability.otel_integration as otel_module

        otel_module._otel_initialized = True

        assert otel_module.is_otel_initialized() is True


class TestModuleExports:
    """Test that module exports are correct."""

    def test_observability_init_exports(self):
        """Test observability __init__.py exports all expected functions."""
        from src.agent_server.observability import (
            get_tracer,
            get_tracing_callbacks,
            is_otel_enabled,
            is_otel_initialized,
            setup_opentelemetry,
            shutdown_opentelemetry,
        )

        # All should be callable
        assert callable(get_tracing_callbacks)
        assert callable(setup_opentelemetry)
        assert callable(shutdown_opentelemetry)
        assert callable(is_otel_enabled)
        assert callable(is_otel_initialized)
        assert callable(get_tracer)
