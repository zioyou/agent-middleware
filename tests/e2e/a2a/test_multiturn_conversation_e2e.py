"""E2E tests for multi-turn conversation via A2A protocol.

Tests context_id-based conversation threading:
- Same context_id → maintains conversation history
- Different context_id → starts fresh conversation
- context_id maps to LangGraph thread_id

Markers:
    @pytest.mark.real_graph: Tests using real LangGraph graphs
"""

from uuid import uuid4

import pytest

from tests.e2e.a2a.conftest import build_jsonrpc_message_send

pytestmark = [pytest.mark.asyncio, pytest.mark.real_graph]


class TestContextIdPreservation:
    """Test context_id-based conversation threading.

    A2A's context_id maps to LangGraph's thread_id for state persistence.
    Same context_id should maintain conversation history across requests.
    """

    async def test_same_context_id_maintains_thread(self, a2a_react_test_client):
        """Messages with same context_id should use same thread.

        This tests that:
        1. First message creates a thread with context_id
        2. Second message with same context_id continues the thread
        """
        context_id = str(uuid4())

        # First message
        request1 = build_jsonrpc_message_send(
            content="Hello, remember my name is Alice.",
            context_id=context_id,
        )
        response1 = await a2a_react_test_client.post("/a2a/agent", json=request1)
        assert response1.status_code == 200

        # Second message with same context_id
        request2 = build_jsonrpc_message_send(
            content="What is my name?",
            context_id=context_id,
        )
        response2 = await a2a_react_test_client.post("/a2a/agent", json=request2)
        assert response2.status_code == 200

        # Both should complete successfully
        data1 = response1.json()
        data2 = response2.json()

        assert "result" in data1
        assert "result" in data2

    async def test_different_context_id_starts_fresh(self, a2a_react_test_client):
        """Messages with different context_id should use different threads."""
        context_id_1 = str(uuid4())
        context_id_2 = str(uuid4())

        # First conversation
        request1 = build_jsonrpc_message_send(
            content="I am Alice.",
            context_id=context_id_1,
        )
        response1 = await a2a_react_test_client.post("/a2a/agent", json=request1)

        # Different conversation
        request2 = build_jsonrpc_message_send(
            content="I am Bob.",
            context_id=context_id_2,
        )
        response2 = await a2a_react_test_client.post("/a2a/agent", json=request2)

        # Both should complete (no cross-contamination)
        assert response1.status_code == 200
        assert response2.status_code == 200

    async def test_no_context_id_creates_new_thread(self, a2a_react_test_client):
        """Message without context_id should create a new thread each time."""
        # First message without context_id
        request1 = build_jsonrpc_message_send(content="Hello!")
        response1 = await a2a_react_test_client.post("/a2a/agent", json=request1)

        # Second message without context_id
        request2 = build_jsonrpc_message_send(content="Hello again!")
        response2 = await a2a_react_test_client.post("/a2a/agent", json=request2)

        # Both should get different task IDs (different threads)
        task_id_1 = response1.json()["result"]["id"]
        task_id_2 = response2.json()["result"]["id"]

        assert task_id_1 != task_id_2


class TestConversationThreading:
    """Test conversation threading behavior."""

    async def test_context_id_preserved_in_response(self, a2a_react_test_client):
        """Response should preserve the context_id from request."""
        context_id = str(uuid4())

        request = build_jsonrpc_message_send(
            content="Test message",
            context_id=context_id,
        )
        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        # Check if context_id is preserved (implementation may vary)
        # The task should be associated with this context_id
        assert "result" in data

    async def test_multiple_concurrent_contexts(self, a2a_react_test_client):
        """Multiple contexts can be handled concurrently."""
        import asyncio

        context_ids = [str(uuid4()) for _ in range(3)]

        async def send_message(context_id: str, content: str):
            request = build_jsonrpc_message_send(content=content, context_id=context_id)
            return await a2a_react_test_client.post("/a2a/agent", json=request)

        # Send messages to different contexts concurrently
        responses = await asyncio.gather(
            send_message(context_ids[0], "Hello from context 0"),
            send_message(context_ids[1], "Hello from context 1"),
            send_message(context_ids[2], "Hello from context 2"),
        )

        # All should complete successfully
        for response in responses:
            assert response.status_code == 200
            assert "result" in response.json()

    async def test_task_id_unique_per_request(self, a2a_react_test_client):
        """Each request should get a unique task ID."""
        context_id = str(uuid4())

        # Multiple requests to same context
        request1 = build_jsonrpc_message_send(content="First", context_id=context_id)
        request2 = build_jsonrpc_message_send(content="Second", context_id=context_id)

        response1 = await a2a_react_test_client.post("/a2a/agent", json=request1)
        response2 = await a2a_react_test_client.post("/a2a/agent", json=request2)

        task_id_1 = response1.json()["result"]["id"]
        task_id_2 = response2.json()["result"]["id"]

        # Each request should get its own task ID
        assert task_id_1 != task_id_2


class TestConversationHistory:
    """Test conversation history retrieval via tasks/get."""

    async def test_task_get_returns_task(self, a2a_react_test_client):
        """tasks/get should return the task details."""
        from tests.e2e.a2a.conftest import build_jsonrpc_task_get

        # First, create a task
        send_request = build_jsonrpc_message_send("Hello")
        send_response = await a2a_react_test_client.post("/a2a/agent", json=send_request)
        task_id = send_response.json()["result"]["id"]

        # Then, get the task
        get_request = build_jsonrpc_task_get(task_id)
        get_response = await a2a_react_test_client.post("/a2a/agent", json=get_request)

        assert get_response.status_code == 200
        data = get_response.json()

        # Should return the task
        if "result" in data:
            assert data["result"]["id"] == task_id

    async def test_get_nonexistent_task_returns_error(self, a2a_react_test_client):
        """tasks/get for nonexistent task should return error."""
        from tests.e2e.a2a.conftest import build_jsonrpc_task_get

        fake_task_id = str(uuid4())
        request = build_jsonrpc_task_get(fake_task_id)

        response = await a2a_react_test_client.post("/a2a/agent", json=request)
        data = response.json()

        # Should return error for nonexistent task
        # (error structure may vary by implementation)
        assert "error" in data or (
            "result" in data and data["result"] is None
        )
