"""W3C Trace Context compatible distributed execution context for A2A communication."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote


def _generate_trace_id() -> str:
    return secrets.token_hex(16)


def _generate_span_id() -> str:
    return secrets.token_hex(8)


@dataclass
class DistributedExecutionContext:
    """W3C Trace Context compatible distributed execution context.

    Provides distributed tracing, agent chain tracking, and timeout propagation
    for A2A (Agent-to-Agent) communication.
    """

    trace_id: str = field(default_factory=_generate_trace_id)
    span_id: str = field(default_factory=_generate_span_id)
    parent_span_id: str | None = None
    trace_flags: int = 1

    agent_chain: list[str] = field(default_factory=list)
    origin_agent: str = ""
    current_agent: str = ""

    timeout_remaining_ms: int = 30000
    retry_count: int = 0
    max_retries: int = 3

    baggage: dict[str, Any] = field(default_factory=dict)

    _TRACEPARENT_HEADER = "traceparent"
    _TRACESTATE_HEADER = "tracestate"
    _BAGGAGE_HEADER = "baggage"
    _TIMEOUT_HEADER = "x-timeout-remaining-ms"
    _AGENT_CHAIN_HEADER = "x-agent-chain"

    def to_headers(self) -> dict[str, str]:
        """Serialize context to HTTP headers (W3C Trace Context format)."""
        headers: dict[str, str] = {}

        headers[self._TRACEPARENT_HEADER] = f"00-{self.trace_id}-{self.span_id}-{self.trace_flags:02x}"

        tracestate_parts = []
        if self.agent_chain:
            chain_str = ";".join(self.agent_chain)
            tracestate_parts.append(f"langgraph=agent_chain:{chain_str}")
        if self.origin_agent:
            tracestate_parts.append(f"origin={self.origin_agent}")
        if self.current_agent:
            tracestate_parts.append(f"current={self.current_agent}")
        if tracestate_parts:
            headers[self._TRACESTATE_HEADER] = ",".join(tracestate_parts)

        if self.baggage:
            baggage_items = [f"{quote(str(k))}={quote(str(v))}" for k, v in self.baggage.items()]
            headers[self._BAGGAGE_HEADER] = ",".join(baggage_items)

        headers[self._TIMEOUT_HEADER] = str(self.timeout_remaining_ms)
        if self.agent_chain:
            headers[self._AGENT_CHAIN_HEADER] = ",".join(self.agent_chain)

        return headers

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> DistributedExecutionContext:
        """Deserialize context from HTTP headers."""
        headers_lower = {k.lower(): v for k, v in headers.items()}

        trace_id = _generate_trace_id()
        span_id = _generate_span_id()
        parent_span_id: str | None = None
        trace_flags = 1

        traceparent = headers_lower.get(cls._TRACEPARENT_HEADER, "")
        if traceparent:
            parts = traceparent.split("-")
            if len(parts) >= 4:
                trace_id = parts[1]
                parent_span_id = parts[2]
                span_id = _generate_span_id()
                try:
                    trace_flags = int(parts[3], 16)
                except ValueError:
                    trace_flags = 1

        agent_chain: list[str] = []
        origin_agent = ""
        current_agent = ""

        tracestate = headers_lower.get(cls._TRACESTATE_HEADER, "")
        if tracestate:
            for item in tracestate.split(","):
                item = item.strip()
                if item.startswith("langgraph=agent_chain:"):
                    chain_str = item[len("langgraph=agent_chain:") :]
                    agent_chain = [a.strip() for a in chain_str.split(";") if a.strip()]
                elif item.startswith("origin="):
                    origin_agent = item[len("origin=") :]
                elif item.startswith("current="):
                    current_agent = item[len("current=") :]

        baggage: dict[str, Any] = {}
        baggage_str = headers_lower.get(cls._BAGGAGE_HEADER, "")
        if baggage_str:
            for item in baggage_str.split(","):
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    baggage[unquote(k)] = unquote(v)

        timeout_remaining_ms = 30000
        timeout_str = headers_lower.get(cls._TIMEOUT_HEADER, "")
        if timeout_str:
            try:
                timeout_remaining_ms = int(timeout_str)
            except ValueError:
                pass

        return cls(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            trace_flags=trace_flags,
            agent_chain=agent_chain,
            origin_agent=origin_agent,
            current_agent=current_agent,
            timeout_remaining_ms=timeout_remaining_ms,
            baggage=baggage,
        )

    def create_child_context(self, agent_id: str) -> DistributedExecutionContext:
        """Create a child context for calling a downstream agent."""
        new_chain = self.agent_chain.copy()
        new_chain.append(agent_id)

        return DistributedExecutionContext(
            trace_id=self.trace_id,
            span_id=_generate_span_id(),
            parent_span_id=self.span_id,
            trace_flags=self.trace_flags,
            agent_chain=new_chain,
            origin_agent=self.origin_agent or self.current_agent,
            current_agent=agent_id,
            timeout_remaining_ms=self.timeout_remaining_ms,
            retry_count=0,
            max_retries=self.max_retries,
            baggage=self.baggage.copy(),
        )

    def update_timeout(self, elapsed_ms: int) -> None:
        """Update remaining timeout after some time has elapsed."""
        self.timeout_remaining_ms = max(0, self.timeout_remaining_ms - elapsed_ms)

    def is_timeout_exceeded(self) -> bool:
        """Check if the timeout has been exceeded."""
        return self.timeout_remaining_ms <= 0

    def can_retry(self) -> bool:
        """Check if a retry is allowed."""
        return self.retry_count < self.max_retries and not self.is_timeout_exceeded()

    def increment_retry(self) -> None:
        """Increment the retry counter."""
        self.retry_count += 1

    def get_chain_depth(self) -> int:
        """Get the current depth of the agent chain."""
        return len(self.agent_chain)

    def is_cyclic(self, agent_id: str) -> bool:
        """Check if adding an agent would create a cycle."""
        return agent_id in self.agent_chain

    def add_baggage(self, key: str, value: Any) -> None:
        """Add an item to the baggage."""
        self.baggage[key] = value

    def get_baggage(self, key: str, default: Any = None) -> Any:
        """Get an item from the baggage."""
        return self.baggage.get(key, default)
