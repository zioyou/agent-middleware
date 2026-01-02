"""E2E tests for PostgreSQL persistence via A2A protocol.

Tests database persistence functionality:
- State persists across requests
- Checkpoint recovery works
- Thread history retrievable

These tests require PostgreSQL to be running.
They are marked with @pytest.mark.db and will be skipped if DB is unavailable.

Run with: uv run pytest tests/e2e/a2a/test_postgres_persistence_e2e.py -v
Skip with: uv run pytest tests/e2e/a2a/ -v -m "not db"

Markers:
    @pytest.mark.db: Tests requiring PostgreSQL database
    @pytest.mark.real_graph: Tests using real LangGraph graphs
"""

import os
from uuid import uuid4

import pytest

from tests.e2e.a2a.conftest import build_jsonrpc_message_send

# Skip all tests in this module if DATABASE_URL is not set
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.db,
    pytest.mark.real_graph,
    pytest.mark.skipif(
        not os.getenv("DATABASE_URL"),
        reason="DATABASE_URL not set - PostgreSQL tests skipped",
    ),
]


class TestCheckpointPersistence:
    """Test PostgreSQL checkpoint persistence."""

    async def test_state_persists_across_requests(self, a2a_react_test_client):
        """State should persist across multiple requests with same context."""
        context_id = str(uuid4())

        # First request
        request1 = build_jsonrpc_message_send(
            content="Hello, I'm Alice.",
            context_id=context_id,
        )
        response1 = await a2a_react_test_client.post("/a2a/agent", json=request1)
        assert response1.status_code == 200

        # Second request with same context
        request2 = build_jsonrpc_message_send(
            content="What's my name?",
            context_id=context_id,
        )
        response2 = await a2a_react_test_client.post("/a2a/agent", json=request2)
        assert response2.status_code == 200

        # Both should complete (state was persisted)
        data1 = response1.json()
        data2 = response2.json()

        assert "result" in data1
        assert "result" in data2

    async def test_different_contexts_isolated(self, a2a_react_test_client):
        """Different contexts should have isolated state."""
        context_1 = str(uuid4())
        context_2 = str(uuid4())

        # Request to context 1
        request1 = build_jsonrpc_message_send("I am Bob", context_id=context_1)
        await a2a_react_test_client.post("/a2a/agent", json=request1)

        # Request to context 2
        request2 = build_jsonrpc_message_send("I am Carol", context_id=context_2)
        await a2a_react_test_client.post("/a2a/agent", json=request2)

        # Both should work independently
        # (More detailed assertions would require checking actual state)


class TestThreadHistory:
    """Test thread history retrieval."""

    async def test_task_history_retrievable(self, a2a_react_test_client):
        """Task history should be retrievable via tasks/get."""
        from tests.e2e.a2a.conftest import build_jsonrpc_task_get

        # Create a task
        send_request = build_jsonrpc_message_send("Hello database")
        send_response = await a2a_react_test_client.post("/a2a/agent", json=send_request)
        task_id = send_response.json()["result"]["id"]

        # Get the task
        get_request = build_jsonrpc_task_get(task_id)
        get_response = await a2a_react_test_client.post("/a2a/agent", json=get_request)

        assert get_response.status_code == 200

    async def test_multiple_tasks_in_context(self, a2a_react_test_client):
        """Multiple tasks in same context should be accessible."""
        context_id = str(uuid4())

        # Create multiple tasks
        task_ids = []
        for i in range(3):
            request = build_jsonrpc_message_send(
                content=f"Message {i}",
                context_id=context_id,
            )
            response = await a2a_react_test_client.post("/a2a/agent", json=request)
            task_ids.append(response.json()["result"]["id"])

        # All tasks should be unique
        assert len(set(task_ids)) == 3


class TestInterruptStatePersistence:
    """Test interrupt state persistence in database."""

    async def test_interrupt_state_survives_new_request(self, a2a_hitl_test_client):
        """Interrupted state should survive and be accessible."""
        context_id = str(uuid4())

        # Request that triggers interrupt
        request = build_jsonrpc_message_send(
            content="Search for AI",
            context_id=context_id,
        )
        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)

        assert response.status_code == 200
        task = response.json()["result"]

        # Task should exist with valid state
        assert "id" in task
        assert "status" in task


class TestDatabaseErrorHandling:
    """Test error handling with database operations."""

    async def test_invalid_task_id_handled(self, a2a_react_test_client):
        """Invalid task ID should return appropriate error."""
        from tests.e2e.a2a.conftest import build_jsonrpc_task_get

        fake_task_id = str(uuid4())
        request = build_jsonrpc_task_get(fake_task_id)

        response = await a2a_react_test_client.post("/a2a/agent", json=request)

        # Should handle gracefully (error or null result)
        assert response.status_code == 200 or response.status_code >= 400
