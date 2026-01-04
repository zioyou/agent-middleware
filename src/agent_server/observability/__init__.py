"""Observability module for the agent server.

이 모듈은 Open LangGraph Platform의 관찰성(Observability) 기능을 제공합니다.

지원하는 관찰성 백엔드:
- Langfuse: LLM 추적 및 분석 (LANGFUSE_LOGGING=true)
- OpenTelemetry: 분산 추적 (OTEL_ENABLED=true)

사용 예:
    ```python
    # Langfuse 콜백 (LangGraph/LangChain용)
    from src.agent_server.observability import get_tracing_callbacks
    callbacks = get_tracing_callbacks()

    # OpenTelemetry 설정 (FastAPI 앱용)
    from src.agent_server.observability import setup_opentelemetry
    setup_opentelemetry(app)

    # 트레이싱 데코레이터 사용
    from src.agent_server.observability import trace_function, trace_service_method

    @trace_function(name="my_operation")
    async def my_function():
        ...

    class MyService:
        @trace_service_method(service_name="MyService")
        async def do_something(self):
            ...
    ```
"""

from .langfuse_integration import get_tracing_callbacks
from .otel_integration import (
    get_tracer,
    is_otel_enabled,
    is_otel_initialized,
    setup_opentelemetry,
    shutdown_opentelemetry,
)
from .auto_tracing import TRACED_ATTRIBUTES, TracedService, traced_service
from .tracing import (
    is_tracing_enabled,
    trace_function,
    trace_graph_execution,
    trace_service_method,
)

__all__ = [
    # Langfuse
    "get_tracing_callbacks",
    # OpenTelemetry - Setup
    "setup_opentelemetry",
    "shutdown_opentelemetry",
    "is_otel_enabled",
    "is_otel_initialized",
    "get_tracer",
    # OpenTelemetry - Tracing Decorators
    "trace_function",
    "trace_graph_execution",
    "trace_service_method",
    "is_tracing_enabled",
    # Auto-Tracing
    "TracedService",
    "traced_service",
    "TRACED_ATTRIBUTES",
]
