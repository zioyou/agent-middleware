"""Unit tests for DistributedExecutionContext."""

import pytest

from src.agent_server.services.federation.context_propagation import (
    DistributedExecutionContext,
)


class TestDistributedExecutionContext:
    """Test cases for DistributedExecutionContext."""

    def test_default_initialization(self):
        ctx = DistributedExecutionContext()

        assert len(ctx.trace_id) == 32
        assert len(ctx.span_id) == 16
        assert ctx.parent_span_id is None
        assert ctx.trace_flags == 1
        assert ctx.agent_chain == []
        assert ctx.origin_agent == ""
        assert ctx.current_agent == ""
        assert ctx.timeout_remaining_ms == 30000
        assert ctx.retry_count == 0
        assert ctx.max_retries == 3
        assert ctx.baggage == {}

    def test_custom_initialization(self):
        ctx = DistributedExecutionContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id="c" * 16,
            trace_flags=0,
            agent_chain=["agent1", "agent2"],
            origin_agent="agent1",
            current_agent="agent2",
            timeout_remaining_ms=5000,
            retry_count=1,
            max_retries=5,
            baggage={"key": "value"},
        )

        assert ctx.trace_id == "a" * 32
        assert ctx.span_id == "b" * 16
        assert ctx.parent_span_id == "c" * 16
        assert ctx.trace_flags == 0
        assert ctx.agent_chain == ["agent1", "agent2"]
        assert ctx.origin_agent == "agent1"
        assert ctx.current_agent == "agent2"
        assert ctx.timeout_remaining_ms == 5000
        assert ctx.retry_count == 1
        assert ctx.max_retries == 5
        assert ctx.baggage == {"key": "value"}


class TestToHeaders:
    """Test cases for to_headers serialization."""

    def test_traceparent_header_format(self):
        ctx = DistributedExecutionContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            trace_flags=1,
        )
        headers = ctx.to_headers()

        assert headers["traceparent"] == f"00-{'a' * 32}-{'b' * 16}-01"

    def test_traceparent_with_zero_flags(self):
        ctx = DistributedExecutionContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            trace_flags=0,
        )
        headers = ctx.to_headers()

        assert headers["traceparent"] == f"00-{'a' * 32}-{'b' * 16}-00"

    def test_tracestate_with_agent_chain(self):
        ctx = DistributedExecutionContext(
            agent_chain=["agent1", "agent2"],
            origin_agent="agent1",
            current_agent="agent2",
        )
        headers = ctx.to_headers()

        assert "langgraph=agent_chain:agent1;agent2" in headers["tracestate"]
        assert "origin=agent1" in headers["tracestate"]
        assert "current=agent2" in headers["tracestate"]

    def test_baggage_header(self):
        ctx = DistributedExecutionContext(
            baggage={"user_id": "123", "session": "abc"},
        )
        headers = ctx.to_headers()

        assert "baggage" in headers
        assert "user_id=123" in headers["baggage"]
        assert "session=abc" in headers["baggage"]

    def test_timeout_header(self):
        ctx = DistributedExecutionContext(timeout_remaining_ms=15000)
        headers = ctx.to_headers()

        assert headers["x-timeout-remaining-ms"] == "15000"

    def test_agent_chain_header(self):
        ctx = DistributedExecutionContext(agent_chain=["a", "b", "c"])
        headers = ctx.to_headers()

        assert headers["x-agent-chain"] == "a,b,c"


class TestFromHeaders:
    """Test cases for from_headers deserialization."""

    def test_parse_traceparent(self):
        headers = {"traceparent": f"00-{'a' * 32}-{'b' * 16}-01"}
        ctx = DistributedExecutionContext.from_headers(headers)

        assert ctx.trace_id == "a" * 32
        assert ctx.parent_span_id == "b" * 16
        assert ctx.trace_flags == 1
        assert len(ctx.span_id) == 16
        assert ctx.span_id != "b" * 16

    def test_parse_tracestate_with_agent_chain(self):
        headers = {"tracestate": "langgraph=agent_chain:agent1;agent2,origin=agent1,current=agent2"}
        ctx = DistributedExecutionContext.from_headers(headers)

        assert ctx.agent_chain == ["agent1", "agent2"]
        assert ctx.origin_agent == "agent1"
        assert ctx.current_agent == "agent2"

    def test_parse_baggage(self):
        headers = {"baggage": "user_id=123,session=abc"}
        ctx = DistributedExecutionContext.from_headers(headers)

        assert ctx.baggage == {"user_id": "123", "session": "abc"}

    def test_parse_timeout_header(self):
        headers = {"x-timeout-remaining-ms": "5000"}
        ctx = DistributedExecutionContext.from_headers(headers)

        assert ctx.timeout_remaining_ms == 5000

    def test_case_insensitive_headers(self):
        headers = {
            "Traceparent": f"00-{'a' * 32}-{'b' * 16}-01",
            "X-Timeout-Remaining-Ms": "10000",
        }
        ctx = DistributedExecutionContext.from_headers(headers)

        assert ctx.trace_id == "a" * 32
        assert ctx.timeout_remaining_ms == 10000

    def test_missing_headers_uses_defaults(self):
        ctx = DistributedExecutionContext.from_headers({})

        assert len(ctx.trace_id) == 32
        assert len(ctx.span_id) == 16
        assert ctx.timeout_remaining_ms == 30000
        assert ctx.agent_chain == []


class TestRoundtrip:
    """Test header serialization/deserialization roundtrip."""

    def test_roundtrip_preserves_data(self):
        original = DistributedExecutionContext(
            trace_id="a" * 32,
            span_id="b" * 16,
            trace_flags=1,
            agent_chain=["agent1", "agent2"],
            origin_agent="agent1",
            current_agent="agent2",
            timeout_remaining_ms=15000,
            baggage={"key": "value"},
        )

        headers = original.to_headers()
        restored = DistributedExecutionContext.from_headers(headers)

        assert restored.trace_id == original.trace_id
        assert restored.parent_span_id == original.span_id
        assert restored.trace_flags == original.trace_flags
        assert restored.agent_chain == original.agent_chain
        assert restored.origin_agent == original.origin_agent
        assert restored.current_agent == original.current_agent
        assert restored.timeout_remaining_ms == original.timeout_remaining_ms
        assert restored.baggage == original.baggage


class TestCreateChildContext:
    """Test cases for create_child_context."""

    def test_child_context_inherits_trace_id(self):
        parent = DistributedExecutionContext(trace_id="a" * 32)
        child = parent.create_child_context("child_agent")

        assert child.trace_id == parent.trace_id

    def test_child_context_sets_parent_span_id(self):
        parent = DistributedExecutionContext(span_id="b" * 16)
        child = parent.create_child_context("child_agent")

        assert child.parent_span_id == parent.span_id
        assert child.span_id != parent.span_id

    def test_child_context_extends_agent_chain(self):
        parent = DistributedExecutionContext(agent_chain=["agent1"])
        child = parent.create_child_context("agent2")

        assert child.agent_chain == ["agent1", "agent2"]
        assert parent.agent_chain == ["agent1"]

    def test_child_context_sets_current_agent(self):
        parent = DistributedExecutionContext(current_agent="parent")
        child = parent.create_child_context("child")

        assert child.current_agent == "child"
        assert child.origin_agent == "parent"

    def test_child_context_inherits_timeout(self):
        parent = DistributedExecutionContext(timeout_remaining_ms=5000)
        child = parent.create_child_context("child")

        assert child.timeout_remaining_ms == 5000

    def test_child_context_resets_retry_count(self):
        parent = DistributedExecutionContext(retry_count=2)
        child = parent.create_child_context("child")

        assert child.retry_count == 0

    def test_child_context_copies_baggage(self):
        parent = DistributedExecutionContext(baggage={"key": "value"})
        child = parent.create_child_context("child")

        assert child.baggage == {"key": "value"}
        child.baggage["new_key"] = "new_value"
        assert "new_key" not in parent.baggage


class TestTimeoutManagement:
    """Test cases for timeout management methods."""

    def test_update_timeout_decreases_remaining(self):
        ctx = DistributedExecutionContext(timeout_remaining_ms=10000)
        ctx.update_timeout(3000)

        assert ctx.timeout_remaining_ms == 7000

    def test_update_timeout_does_not_go_negative(self):
        ctx = DistributedExecutionContext(timeout_remaining_ms=5000)
        ctx.update_timeout(10000)

        assert ctx.timeout_remaining_ms == 0

    def test_is_timeout_exceeded_when_zero(self):
        ctx = DistributedExecutionContext(timeout_remaining_ms=0)

        assert ctx.is_timeout_exceeded() is True

    def test_is_timeout_exceeded_when_remaining(self):
        ctx = DistributedExecutionContext(timeout_remaining_ms=1000)

        assert ctx.is_timeout_exceeded() is False


class TestRetryManagement:
    """Test cases for retry management methods."""

    def test_can_retry_when_under_limit(self):
        ctx = DistributedExecutionContext(retry_count=1, max_retries=3)

        assert ctx.can_retry() is True

    def test_cannot_retry_when_at_limit(self):
        ctx = DistributedExecutionContext(retry_count=3, max_retries=3)

        assert ctx.can_retry() is False

    def test_cannot_retry_when_timeout_exceeded(self):
        ctx = DistributedExecutionContext(retry_count=0, max_retries=3, timeout_remaining_ms=0)

        assert ctx.can_retry() is False

    def test_increment_retry(self):
        ctx = DistributedExecutionContext(retry_count=0)
        ctx.increment_retry()

        assert ctx.retry_count == 1


class TestChainManagement:
    """Test cases for agent chain management."""

    def test_get_chain_depth(self):
        ctx = DistributedExecutionContext(agent_chain=["a", "b", "c"])

        assert ctx.get_chain_depth() == 3

    def test_get_chain_depth_empty(self):
        ctx = DistributedExecutionContext()

        assert ctx.get_chain_depth() == 0

    def test_is_cyclic_when_agent_in_chain(self):
        ctx = DistributedExecutionContext(agent_chain=["agent1", "agent2"])

        assert ctx.is_cyclic("agent1") is True
        assert ctx.is_cyclic("agent2") is True

    def test_is_cyclic_when_agent_not_in_chain(self):
        ctx = DistributedExecutionContext(agent_chain=["agent1"])

        assert ctx.is_cyclic("agent2") is False


class TestBaggageManagement:
    """Test cases for baggage management."""

    def test_add_baggage(self):
        ctx = DistributedExecutionContext()
        ctx.add_baggage("key", "value")

        assert ctx.baggage == {"key": "value"}

    def test_get_baggage_existing(self):
        ctx = DistributedExecutionContext(baggage={"key": "value"})

        assert ctx.get_baggage("key") == "value"

    def test_get_baggage_missing_returns_default(self):
        ctx = DistributedExecutionContext()

        assert ctx.get_baggage("missing") is None
        assert ctx.get_baggage("missing", "default") == "default"
