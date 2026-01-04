"""Automatic service method tracing via inheritance.

Provides TracedService base class and @traced_service decorator for
automatic OpenTelemetry tracing of all public methods.

When OTEL_ENABLED=false, NO wrapping occurs (zero overhead).

Usage:
    ```python
    # Option 1: Inheritance
    class MyService(TracedService):
        async def create_item(self, item_id: str) -> Item:
            ...  # Automatically traced with span attributes

    # Option 2: Decorator
    @traced_service
    class MyService:
        async def get_item(self, assistant_id: str) -> Item:
            ...  # assistant_id auto-extracted to span attribute
    ```

Auto-extracted span attributes:
    - assistant_id -> service.assistant_id
    - thread_id -> service.thread_id
    - run_id -> service.run_id
    - graph_id -> service.graph_id
    - user_id -> service.user_id
    - namespace -> service.namespace

Exclusion:
    - Methods starting with `_` are never traced
    - Add method names to `__trace_exclude__` class attribute to exclude
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from .otel_integration import get_tracer, is_otel_enabled
from .tracing import _set_span_attributes, _set_span_error_status, _set_span_ok_status

logger = logging.getLogger(__name__)

C = TypeVar("C", bound=type)

TRACED_ATTRIBUTES: dict[str, str] = {
    "assistant_id": "service.assistant_id",
    "thread_id": "service.thread_id",
    "run_id": "service.run_id",
    "graph_id": "service.graph_id",
    "user_id": "service.user_id",
    "namespace": "service.namespace",
    "limit": "service.limit",
    "offset": "service.offset",
}


def _extract_trace_attributes(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    attributes: dict[str, Any] = {}

    try:
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())
    except (ValueError, TypeError):
        param_names = []

    combined_args: dict[str, Any] = dict(kwargs)
    for i, arg in enumerate(args):
        if i < len(param_names):
            combined_args[param_names[i]] = arg

    for arg_name, attr_name in TRACED_ATTRIBUTES.items():
        if arg_name in combined_args:
            value = combined_args[arg_name]
            if value is not None:
                attributes[attr_name] = str(value)

    return attributes


def _wrap_method(
    method: Callable[..., Any],
    service_name: str,
) -> Callable[..., Any]:
    span_name = f"service.{service_name}.{method.__name__}"
    tracer = get_tracer(__name__)

    if asyncio.iscoroutinefunction(method):

        @functools.wraps(method)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("service.name", service_name)
                span.set_attribute("service.method", method.__name__)
                span.set_attribute("code.function", method.__name__)
                span.set_attribute("code.namespace", method.__module__)

                extracted = _extract_trace_attributes(method, args, kwargs)
                _set_span_attributes(span, extracted)

                try:
                    result = await method(*args, **kwargs)
                    _set_span_ok_status(span)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("service.error", True)
                    _set_span_error_status(span, e)
                    raise

        return async_wrapper
    else:

        @functools.wraps(method)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("service.name", service_name)
                span.set_attribute("service.method", method.__name__)
                span.set_attribute("code.function", method.__name__)
                span.set_attribute("code.namespace", method.__module__)

                extracted = _extract_trace_attributes(method, args, kwargs)
                _set_span_attributes(span, extracted)

                try:
                    result = method(*args, **kwargs)
                    _set_span_ok_status(span)
                    return result
                except Exception as e:
                    span.record_exception(e)
                    span.set_attribute("service.error", True)
                    _set_span_error_status(span, e)
                    raise

        return sync_wrapper


def _should_trace_method(name: str, method: Any, exclude_set: set[str]) -> bool:
    if name.startswith("_"):
        return False

    if name in exclude_set:
        return False

    if not callable(method):
        return False

    if isinstance(inspect.getattr_static(type(method), name, None), (classmethod, staticmethod)):
        return False

    return True


def _instrument_class(cls: type) -> type:
    if not is_otel_enabled():
        logger.debug(f"OTEL disabled, skipping instrumentation for {cls.__name__}")
        return cls

    service_name = cls.__name__
    exclude_set: set[str] = set(getattr(cls, "__trace_exclude__", []))

    for name in list(vars(cls)):
        attr = getattr(cls, name, None)

        if not _should_trace_method(name, attr, exclude_set):
            continue

        raw_attr = vars(cls).get(name)
        if raw_attr is None:
            continue

        if isinstance(raw_attr, staticmethod):
            continue
        if isinstance(raw_attr, classmethod):
            continue

        if callable(raw_attr):
            wrapped = _wrap_method(raw_attr, service_name)
            setattr(cls, name, wrapped)
            logger.debug(f"Instrumented {service_name}.{name}")

    return cls


class TracedService:
    """Base class for automatic method tracing.

    Inherit from this class to auto-trace all public methods.
    Zero overhead when OTEL_ENABLED=false.

    Attributes:
        __trace_exclude__: List of method names to skip tracing.
    """

    __trace_exclude__: list[str] = []

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        _instrument_class(cls)


def traced_service(cls: C) -> C:
    """Class decorator for automatic method tracing.

    Alternative to TracedService inheritance.
    Zero overhead when OTEL_ENABLED=false.
    """
    return _instrument_class(cls)  # type: ignore[return-value]
