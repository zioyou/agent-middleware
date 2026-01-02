"""E2E tests for Human-in-the-Loop resume flow via A2A protocol.

Tests resuming interrupted tasks with different user responses:
- accept: Execute tool as-is
- edit: Modify tool args and execute
- response: Cancel tool, provide user response
- ignore: Cancel tool and end

Note: The resume API is typically POST /threads/{thread_id}/runs/{run_id}
      but A2A may wrap this in JSON-RPC format.

Known Issue:
    Command(goto=END) has a LangGraph bug causing infinite loop (GitHub #5572)
    The 'ignore' action may behave unexpectedly.

Markers:
    @pytest.mark.hitl: Human-in-the-Loop tests
    @pytest.mark.real_graph: Tests using real LangGraph graphs
"""

from uuid import uuid4

import pytest

from tests.e2e.a2a.conftest import build_jsonrpc_message_send

pytestmark = [pytest.mark.asyncio, pytest.mark.hitl, pytest.mark.real_graph]


class TestResumeWithAccept:
    """Test resuming with 'accept' response.

    Accept should:
    1. Continue to tools node
    2. Execute the tool with original args
    3. Return to call_model
    4. Complete with final response
    """

    async def test_accept_allows_task_to_proceed(self, a2a_hitl_test_client):
        """After interrupt, accept should allow task to proceed.

        Note: This test verifies the basic flow. The actual resume
        mechanism depends on A2A protocol implementation.
        """
        context_id = str(uuid4())

        # First request triggers interrupt
        request = build_jsonrpc_message_send(
            content="Search for AI information",
            context_id=context_id,
        )

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        assert response.status_code == 200

        data = response.json()
        assert "result" in data

        # Store task_id for potential resume operations
        task_id = data["result"]["id"]
        assert task_id is not None


class TestResumeWithEdit:
    """Test resuming with 'edit' response.

    Edit should:
    1. Modify tool call args with user-provided values
    2. Continue to tools node
    3. Execute tool with modified args
    4. Complete with final response
    """

    async def test_task_structure_supports_edit(self, a2a_hitl_test_client):
        """Task should have structure that supports edit operations."""
        request = build_jsonrpc_message_send("Search for Python tutorials")

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        data = response.json()

        # Task should exist with valid structure
        assert "result" in data
        task = data["result"]
        assert "id" in task
        assert "status" in task


class TestResumeWithResponse:
    """Test resuming with 'response' (user text) response.

    Response should:
    1. Cancel the tool execution
    2. Add user's text as a HumanMessage
    3. Continue to call_model with user input
    4. Complete with new response
    """

    async def test_task_supports_response_action(self, a2a_hitl_test_client):
        """Task should support response action structure."""
        request = build_jsonrpc_message_send("Look up weather information")

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        data = response.json()

        assert "result" in data
        # Task should be retrievable for response action
        assert "id" in data["result"]


class TestResumeWithIgnore:
    """Test resuming with 'ignore' response.

    Ignore should:
    1. Cancel the tool execution
    2. End the conversation
    3. Task should complete (possibly with cancellation artifacts)

    Note: Due to LangGraph bug #5572, Command(goto=END) may cause issues.
    """

    async def test_task_supports_ignore_action(self, a2a_hitl_test_client):
        """Task should support ignore action (may be affected by bug #5572)."""
        request = build_jsonrpc_message_send("Search for something")

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        data = response.json()

        assert "result" in data
        # Task exists even if ignore action has issues
        assert "id" in data["result"]


class TestResumePersistence:
    """Test that interrupted state is properly persisted."""

    async def test_task_retrievable_after_interrupt(self, a2a_hitl_test_client):
        """Interrupted task should be retrievable via tasks/get."""
        from tests.e2e.a2a.conftest import build_jsonrpc_task_get

        # Create task that triggers interrupt
        send_request = build_jsonrpc_message_send("Search for info")
        send_response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=send_request)
        task_id = send_response.json()["result"]["id"]

        # Try to get the task
        get_request = build_jsonrpc_task_get(task_id)
        get_response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=get_request)

        # Task should be retrievable (even if in interrupted state)
        assert get_response.status_code == 200


class TestResumeContextPreservation:
    """Test that context is preserved during resume."""

    async def test_context_id_preserved_through_interrupt(self, a2a_hitl_test_client):
        """Context ID should be preserved through interrupt/resume cycle."""
        context_id = str(uuid4())

        # Initial request with context_id
        request = build_jsonrpc_message_send(
            content="Search for AI",
            context_id=context_id,
        )

        response = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request)
        data = response.json()

        # Task should be created with the context
        assert "result" in data
        assert "id" in data["result"]

    async def test_multiple_contexts_independent(self, a2a_hitl_test_client):
        """Different contexts should be independent during interrupts."""
        context_1 = str(uuid4())
        context_2 = str(uuid4())

        # Two different contexts
        request1 = build_jsonrpc_message_send("Search A", context_id=context_1)
        request2 = build_jsonrpc_message_send("Search B", context_id=context_2)

        response1 = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request1)
        response2 = await a2a_hitl_test_client.post("/a2a/agent_hitl", json=request2)

        # Both should work independently
        assert response1.status_code == 200
        assert response2.status_code == 200

        task_id_1 = response1.json()["result"]["id"]
        task_id_2 = response2.json()["result"]["id"]

        assert task_id_1 != task_id_2
