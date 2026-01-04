"""Tracing decorators for OpenTelemetry instrumentation.

This module provides decorators for tracing functions and methods with
OpenTelemetry spans. Decorators work seamlessly whether OpenTelemetry is
enabled or disabled (graceful degradation to no-op).

데코레이터 종류:
    - trace_function: 일반 함수/메서드 트레이싱
    - trace_graph_execution: LangGraph 그래프 실행 추적
    - trace_service_method: 서비스 메서드 트레이싱

사용 예:
    ```python
    from src.agent_server.observability.tracing import (
        trace_function,
        trace_graph_execution,
        trace_service_method,
    )

    @trace_function(name="my_operation")
    async def my_async_function():
        ...

    @trace_graph_execution(graph_id="react_agent")
    async def run_agent():
        ...

    class MyService:
        @trace_service_method(service_name="MyService")
        async def do_something(self):
            ...
    ```

참고:
    - OpenTelemetry가 비활성화되어도 데코레이터는 정상 작동 (no-op)
    - sync/async 함수 모두 지원
    - 예외 발생 시 자동으로 span에 기록
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from opentelemetry.trace import Span, StatusCode

from .otel_integration import get_tracer, is_otel_enabled

logger = logging.getLogger(__name__)

# Type variables for generic decorator typing
F = TypeVar("F", bound=Callable[..., Any])

# Check if OpenTelemetry is available
_OTEL_AVAILABLE = False
try:
    from opentelemetry.trace import Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    pass


def _set_span_ok_status(span: Any) -> None:
    """Set span status to OK.

    Args:
        span: OpenTelemetry span (or no-op span)
    """
    if _OTEL_AVAILABLE:
        from opentelemetry.trace import Status, StatusCode

        span.set_status(Status(StatusCode.OK))


def _set_span_error_status(span: Any, error: Exception) -> None:
    """Set span status to ERROR with description.

    Args:
        span: OpenTelemetry span (or no-op span)
        error: The exception that occurred
    """
    if _OTEL_AVAILABLE:
        from opentelemetry.trace import Status, StatusCode

        span.set_status(Status(StatusCode.ERROR, str(error)))


def _set_span_attributes(span: Any, attributes: dict[str, Any] | None) -> None:
    """Safely set span attributes.

    Args:
        span: OpenTelemetry span (or no-op span)
        attributes: Dictionary of attributes to set
    """
    if attributes is None:
        return

    for key, value in attributes.items():
        try:
            # Only set serializable values
            if isinstance(value, (str, int, float, bool)):
                span.set_attribute(key, value)
            elif isinstance(value, (list, tuple)) and all(
                isinstance(v, (str, int, float, bool)) for v in value
            ):
                span.set_attribute(key, list(value))
            else:
                # Convert to string for complex types
                span.set_attribute(key, str(value))
        except Exception:
            # Silently ignore attribute setting errors
            pass


def trace_function(
    name: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    """Decorator for tracing function execution with OpenTelemetry.

    Supports both synchronous and asynchronous functions. When OpenTelemetry
    is disabled or not initialized, the decorator becomes a no-op.

    Args:
        name: Span name. If None, uses the function's qualified name.
        attributes: Additional span attributes to set.

    Returns:
        Decorated function with tracing enabled.

    Example:
        ```python
        @trace_function(name="process_data", attributes={"priority": "high"})
        async def process_data(data: dict) -> dict:
            # Function body...
            return result

        @trace_function()  # Uses function name as span name
        def sync_function():
            pass
        ```
    """

    def decorator(func: F) -> F:
        span_name = name or f"{func.__module__}.{func.__qualname__}"
        tracer = get_tracer(__name__)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                # Set base attributes
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.namespace", func.__module__)

                # Set custom attributes
                _set_span_attributes(span, attributes)

                try:
                    result = await func(*args, **kwargs)
                    _set_span_ok_status(span)
                    return result
                except Exception as e:
                    # Record exception details
                    span.record_exception(e)
                    _set_span_error_status(span, e)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                # Set base attributes
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.namespace", func.__module__)

                # Set custom attributes
                _set_span_attributes(span, attributes)

                try:
                    result = func(*args, **kwargs)
                    _set_span_ok_status(span)
                    return result
                except Exception as e:
                    # Record exception details
                    span.record_exception(e)
                    _set_span_error_status(span, e)
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def trace_graph_execution(graph_id: str) -> Callable[[F], F]:
    """Decorator for tracing LangGraph graph execution.

    Adds LangGraph-specific attributes to spans including graph_id,
    execution phase, and timing information.

    Args:
        graph_id: Identifier for the LangGraph graph being executed.

    Returns:
        Decorated function with graph execution tracing.

    Example:
        ```python
        @trace_graph_execution(graph_id="react_agent")
        async def run_graph(input_data: dict) -> dict:
            # Graph execution logic...
            return result
        ```
    """

    def decorator(func: F) -> F:
        span_name = f"langgraph.execute.{graph_id}"
        tracer = get_tracer(__name__)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                # LangGraph-specific attributes
                span.set_attribute("langgraph.graph_id", graph_id)
                span.set_attribute("langgraph.operation", "execute")
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.namespace", func.__module__)

                # Extract thread_id and run_id from kwargs if available
                if "thread_id" in kwargs:
                    span.set_attribute("langgraph.thread_id", str(kwargs["thread_id"]))
                if "run_id" in kwargs:
                    span.set_attribute("langgraph.run_id", str(kwargs["run_id"]))
                if "assistant_id" in kwargs:
                    span.set_attribute("langgraph.assistant_id", str(kwargs["assistant_id"]))

                try:
                    result = await func(*args, **kwargs)
                    _set_span_ok_status(span)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("langgraph.error", True)
                    span.set_attribute("langgraph.error_type", type(e).__name__)
                    _set_span_error_status(span, e)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                # LangGraph-specific attributes
                span.set_attribute("langgraph.graph_id", graph_id)
                span.set_attribute("langgraph.operation", "execute")
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.namespace", func.__module__)

                # Extract thread_id and run_id from kwargs if available
                if "thread_id" in kwargs:
                    span.set_attribute("langgraph.thread_id", str(kwargs["thread_id"]))
                if "run_id" in kwargs:
                    span.set_attribute("langgraph.run_id", str(kwargs["run_id"]))
                if "assistant_id" in kwargs:
                    span.set_attribute("langgraph.assistant_id", str(kwargs["assistant_id"]))

                try:
                    result = func(*args, **kwargs)
                    _set_span_ok_status(span)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("langgraph.error", True)
                    span.set_attribute("langgraph.error_type", type(e).__name__)
                    _set_span_error_status(span, e)
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def trace_service_method(service_name: str) -> Callable[[F], F]:
    """Decorator for tracing service layer methods.

    Adds service-specific context to spans including service name,
    method name, and operation type.

    Args:
        service_name: Name of the service class (e.g., "AssistantService").

    Returns:
        Decorated method with service tracing.

    Example:
        ```python
        class AssistantService:
            @trace_service_method(service_name="AssistantService")
            async def create_assistant(self, data: dict) -> Assistant:
                # Service method logic...
                return assistant

            @trace_service_method(service_name="AssistantService")
            async def get_assistant(self, assistant_id: str) -> Assistant:
                # Retrieval logic...
                return assistant
        ```
    """

    def decorator(func: F) -> F:
        span_name = f"service.{service_name}.{func.__name__}"
        tracer = get_tracer(__name__)

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                # Service-specific attributes
                span.set_attribute("service.name", service_name)
                span.set_attribute("service.method", func.__name__)
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.namespace", func.__module__)

                try:
                    result = await func(*args, **kwargs)
                    _set_span_ok_status(span)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("service.error", True)
                    _set_span_error_status(span, e)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                # Service-specific attributes
                span.set_attribute("service.name", service_name)
                span.set_attribute("service.method", func.__name__)
                span.set_attribute("code.function", func.__name__)
                span.set_attribute("code.namespace", func.__module__)

                try:
                    result = func(*args, **kwargs)
                    _set_span_ok_status(span)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("service.error", True)
                    _set_span_error_status(span, e)
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


def is_tracing_enabled() -> bool:
    """Check if tracing is currently active.

    Returns True if OTEL_ENABLED=true, regardless of initialization status.
    This allows __init_subclass__ to wrap methods at import time.
    The actual tracer will be a no-op until setup_opentelemetry() is called.

    Returns:
        bool: True if OpenTelemetry is enabled via OTEL_ENABLED environment variable.
    """
    return is_otel_enabled()
