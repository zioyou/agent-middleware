"""W3C Trace Context compatible distributed execution context for A2A communication."""

from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)

# =============================================================================
# Security Constants
# =============================================================================

# W3C Trace Context validation patterns
# https://www.w3.org/TR/trace-context/#traceparent-header
_TRACEPARENT_REGEX = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")
_ZERO_TRACE_ID = "0" * 32
_ZERO_SPAN_ID = "0" * 16

# Size limits to prevent DoS via header bloat
MAX_BAGGAGE_SIZE = 8192  # 8KB max for baggage header
MAX_BAGGAGE_ITEMS = 64  # Max number of baggage items
MAX_AGENT_CHAIN_LENGTH = 32  # Max depth of agent chain (prevent infinite loops)
MAX_TRACESTATE_SIZE = 512  # Max size for tracestate header

# Timeout bounds
MIN_TIMEOUT_MS = 100  # Minimum 100ms timeout
MAX_TIMEOUT_MS = 300000  # Maximum 5 minutes timeout
DEFAULT_TIMEOUT_MS = 30000  # Default 30 seconds


def _generate_trace_id() -> str:
    return secrets.token_hex(16)


def _generate_span_id() -> str:
    return secrets.token_hex(8)


def _validate_traceparent(traceparent: str) -> tuple[str, str, int] | None:
    """Validate W3C traceparent header format.

    Returns:
        Tuple of (trace_id, parent_span_id, trace_flags) if valid, None otherwise.
    """
    if not traceparent or len(traceparent) > 100:
        return None

    match = _TRACEPARENT_REGEX.match(traceparent.lower())
    if not match:
        logger.debug("Invalid traceparent format: %s", traceparent[:50])
        return None

    version, trace_id, parent_span_id, flags_hex = match.groups()

    # Version 00 is currently the only supported version
    # Future versions (01-fe) should be treated as valid but we extract what we understand
    if version == "ff":
        # Version ff is invalid per spec
        logger.debug("Invalid traceparent version ff")
        return None

    # All-zero trace_id or parent_id are invalid per W3C spec
    if trace_id == _ZERO_TRACE_ID:
        logger.debug("Invalid traceparent: all-zero trace_id")
        return None
    if parent_span_id == _ZERO_SPAN_ID:
        logger.debug("Invalid traceparent: all-zero parent_span_id")
        return None

    try:
        trace_flags = int(flags_hex, 16)
    except ValueError:
        trace_flags = 1

    return trace_id, parent_span_id, trace_flags


def _clamp_timeout(timeout_ms: int) -> int:
    """Clamp timeout to safe bounds."""
    return max(MIN_TIMEOUT_MS, min(MAX_TIMEOUT_MS, timeout_ms))


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
        """Deserialize context from HTTP headers with strict validation.

        SECURITY: This method validates all untrusted header values:
        - W3C traceparent format validation (reject malformed)
        - All-zero trace/span IDs are rejected
        - Baggage size limits enforced
        - Agent chain depth limits enforced
        - Timeout values clamped to safe bounds
        """
        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Default values
        trace_id = _generate_trace_id()
        span_id = _generate_span_id()
        parent_span_id: str | None = None
        trace_flags = 1

        # SECURITY: Validate traceparent strictly per W3C spec
        traceparent = headers_lower.get(cls._TRACEPARENT_HEADER, "")
        if traceparent:
            validated = _validate_traceparent(traceparent)
            if validated:
                trace_id, parent_span_id, trace_flags = validated
                span_id = _generate_span_id()  # Always generate new span for this context
            else:
                # Invalid traceparent - generate new trace context
                logger.warning("Rejected invalid traceparent header, generating new trace")

        agent_chain: list[str] = []
        origin_agent = ""
        current_agent = ""

        # SECURITY: Validate tracestate size
        tracestate = headers_lower.get(cls._TRACESTATE_HEADER, "")
        if tracestate and len(tracestate) <= MAX_TRACESTATE_SIZE:
            for item in tracestate.split(","):
                item = item.strip()
                if item.startswith("langgraph=agent_chain:"):
                    chain_str = item[len("langgraph=agent_chain:") :]
                    raw_chain = [a.strip() for a in chain_str.split(";") if a.strip()]
                    # SECURITY: Limit agent chain depth to prevent infinite loops
                    agent_chain = raw_chain[:MAX_AGENT_CHAIN_LENGTH]
                    if len(raw_chain) > MAX_AGENT_CHAIN_LENGTH:
                        logger.warning(
                            "Agent chain truncated from %d to %d entries",
                            len(raw_chain),
                            MAX_AGENT_CHAIN_LENGTH,
                        )
                elif item.startswith("origin="):
                    origin_agent = item[len("origin=") :][:256]  # Limit length
                elif item.startswith("current="):
                    current_agent = item[len("current=") :][:256]  # Limit length
        elif tracestate and len(tracestate) > MAX_TRACESTATE_SIZE:
            logger.warning("Rejected oversized tracestate header (%d bytes)", len(tracestate))

        baggage: dict[str, Any] = {}
        baggage_str = headers_lower.get(cls._BAGGAGE_HEADER, "")
        # SECURITY: Validate baggage size to prevent DoS
        if baggage_str and len(baggage_str) <= MAX_BAGGAGE_SIZE:
            item_count = 0
            for item in baggage_str.split(","):
                if item_count >= MAX_BAGGAGE_ITEMS:
                    logger.warning("Baggage items truncated at %d", MAX_BAGGAGE_ITEMS)
                    break
                item = item.strip()
                if "=" in item:
                    k, v = item.split("=", 1)
                    # Limit key/value sizes
                    key = unquote(k)[:256]
                    value = unquote(v)[:4096]
                    baggage[key] = value
                    item_count += 1
        elif baggage_str and len(baggage_str) > MAX_BAGGAGE_SIZE:
            logger.warning("Rejected oversized baggage header (%d bytes)", len(baggage_str))

        # SECURITY: Clamp timeout to safe bounds
        timeout_remaining_ms = DEFAULT_TIMEOUT_MS
        timeout_str = headers_lower.get(cls._TIMEOUT_HEADER, "")
        if timeout_str:
            try:
                raw_timeout = int(timeout_str)
                timeout_remaining_ms = _clamp_timeout(raw_timeout)
                if raw_timeout != timeout_remaining_ms:
                    logger.debug(
                        "Timeout clamped from %d to %d ms",
                        raw_timeout,
                        timeout_remaining_ms,
                    )
            except ValueError:
                logger.debug("Invalid timeout header value: %s", timeout_str[:20])

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
